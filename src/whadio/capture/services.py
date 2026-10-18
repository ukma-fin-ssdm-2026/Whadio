import asyncio
import io
import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, BinaryIO, Final, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, TypeAdapter

from ..accounts.repositories import MemberWorkspace
from ..meetings.enums import MeetingSource, RecordingStatus
from ..meetings.models import Folder, Meeting
from ..meetings.persistence import AssembledRecording
from ..meetings.services import RecordingInput
from ..processing.speakers import SpeakerEvent
from ..shared.errors import Failure, UseCaseError
from ..shared.storage import ObjectStorageError
from .enums import CaptureStatus
from .models import CaptureSession
from .repositories import ICaptureRepository

if TYPE_CHECKING:
    from pydantic import JsonValue

logger = logging.getLogger(__name__)

MAX_CHUNK_BYTES: Final = 8 * 1024 * 1024
_OPEN: Final = frozenset({CaptureStatus.RECORDING, CaptureStatus.IDLE})


class IChunkStorage(Protocol):
    def put(self, key: str, data: BinaryIO, *, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


class IWorkspaces(Protocol):
    async def list_workspaces(self, user_id: UUID, /) -> list[MemberWorkspace]: ...


class IFolders(Protocol):
    async def folders(self, actor_id: UUID, workspace_id: UUID, /) -> list[Folder]: ...


class IMeetingIngestion(Protocol):
    async def ingest(
        self, actor_id: UUID, workspace_id: UUID, recording: RecordingInput, now: datetime, /
    ) -> Meeting: ...


class IMeetingAccess(Protocol):
    async def workspace_id(self, actor_id: UUID, meeting_id: UUID, /) -> UUID: ...


class IRecordingAttachment(Protocol):
    async def attach_recording(
        self, actor_id: UUID, meeting_id: UUID, recording: AssembledRecording, now: datetime, /
    ) -> None: ...


class ITranscriptionQueue(Protocol):
    async def queue_transcription(self, meeting_id: UUID, /) -> None: ...


@dataclass(frozen=True)
class CaptureCollaborators:
    repository: ICaptureRepository
    storage: IChunkStorage
    workspaces: IWorkspaces
    folders: IFolders
    ingestion: IMeetingIngestion
    access: IMeetingAccess
    recordings: IRecordingAttachment
    processing: ITranscriptionQueue


@dataclass(frozen=True)
class Destination:
    workspace: MemberWorkspace
    folders: list[Folder]


@dataclass(frozen=True)
class CaptureView:
    capture_id: UUID
    meeting_id: UUID
    status: CaptureStatus
    received_seqs: tuple[int, ...]


@dataclass(frozen=True)
class ChunkUpload:
    seq: int
    audio: bytes
    speaker_events: tuple[SpeakerEvent, ...]


class _StoredSpeakerEvent(BaseModel):
    at_seconds: float = Field(description="Seconds from the start of the recording")
    speakers: tuple[str, ...] = Field(description="Participants speaking from that moment on")


_STORED_EVENTS: Final = TypeAdapter(list[_StoredSpeakerEvent])


class CaptureSpeakerTimeline:
    """Processing's `ISpeakerTimeline`: what the extension saw on the Meet page, in recording
    order; none for a meeting that was not captured."""

    def __init__(self, repository: ICaptureRepository) -> None:
        self._repository: ICaptureRepository = repository

    async def speaker_events(self, meeting_id: UUID) -> tuple[SpeakerEvent, ...]:
        return tuple(
            SpeakerEvent(event.at_seconds, event.speakers)
            for chunk in await self._repository.meeting_chunks(meeting_id)
            for event in _STORED_EVENTS.validate_python(chunk.speaker_events or [])
        )


class MissingChunksError(UseCaseError):
    def __init__(self, missing: tuple[int, ...]) -> None:
        super().__init__(Failure.MISSING_CHUNKS)
        self.missing: tuple[int, ...] = missing


class CaptureService:
    """Recordings from the extension, uploaded in numbered chunks and assembled into a meeting.

    Runs inside the caller's transaction. A chunk's object key is fixed by its capture and
    number, so a retried upload overwrites what an earlier, rolled-back attempt left behind.
    Every call rechecks that the account opening the capture is still allowed the meeting.
    """

    def __init__(self, collaborators: CaptureCollaborators) -> None:
        self._repository: ICaptureRepository = collaborators.repository
        self._storage: IChunkStorage = collaborators.storage
        self._workspaces: IWorkspaces = collaborators.workspaces
        self._folders: IFolders = collaborators.folders
        self._ingestion: IMeetingIngestion = collaborators.ingestion
        self._access: IMeetingAccess = collaborators.access
        self._recordings: IRecordingAttachment = collaborators.recordings
        self._processing: ITranscriptionQueue = collaborators.processing

    async def destinations(self, user_id: UUID) -> list[Destination]:
        return [
            Destination(workspace, await self._folders.folders(user_id, workspace.workspace_id))
            for workspace in await self._workspaces.list_workspaces(user_id)
        ]

    async def start(
        self,
        user_id: UUID,
        workspace_id: UUID | None,
        folder_id: UUID | None,
        *,
        consent_confirmed: bool,
        now: datetime,
    ) -> CaptureView:
        if not consent_confirmed:
            raise UseCaseError(Failure.VALIDATION_ERROR)
        if workspace_id is None:
            if folder_id is not None:
                raise UseCaseError(Failure.VALIDATION_ERROR)
            workspace_id = next(
                item.workspace_id
                for item in await self._workspaces.list_workspaces(user_id)
                if item.is_personal
            )
        meeting = await self._ingestion.ingest(
            user_id,
            workspace_id,
            RecordingInput(
                None,
                now,
                MeetingSource.EXTENSION,
                folder_id=folder_id,
                consent_confirmed_at=now,
            ),
            now,
        )
        capture = await self._repository.open(meeting.meeting_id, user_id, now)
        return CaptureView(capture.capture_session_id, meeting.meeting_id, capture.status, ())

    async def get(self, user_id: UUID, capture_id: UUID) -> CaptureView:
        capture = await self._own(user_id, capture_id, lock=False)
        return await self._view(capture, capture.status)

    async def put_chunk(
        self, user_id: UUID, capture_id: UUID, chunk: ChunkUpload, now: datetime
    ) -> bool:
        """Store one chunk; False when the same audio was already stored under its number."""
        if chunk.seq < 0 or not chunk.audio or len(chunk.audio) > MAX_CHUNK_BYTES:
            raise UseCaseError(Failure.VALIDATION_ERROR)
        capture = await self._own(user_id, capture_id, lock=True)
        if capture.status not in _OPEN:
            raise UseCaseError(Failure.CAPTURE_CLOSED)
        stored = await self._repository.chunk(capture_id, chunk.seq)
        if stored is not None:
            if await self._read(stored.storage_key) != chunk.audio:
                raise UseCaseError(Failure.CHUNK_MISMATCH)
            return False
        key = f"captures/{capture_id}/{chunk.seq}"
        await self._put(key, io.BytesIO(chunk.audio))
        events: JsonValue = [
            {"at_seconds": event.at_seconds, "speakers": list(event.speakers)}
            for event in chunk.speaker_events
        ]
        await self._repository.add_chunk(capture_id, chunk.seq, key, events, now)
        return True

    async def complete(
        self, user_id: UUID, capture_id: UUID, last_seq: int, now: datetime
    ) -> CaptureView:
        if last_seq < 0:
            raise UseCaseError(Failure.VALIDATION_ERROR)
        capture = await self._own(user_id, capture_id, lock=True)
        if capture.status is CaptureStatus.ASSEMBLED and capture.last_chunk_seq == last_seq:
            return await self._view(capture, capture.status)
        if capture.status not in _OPEN:
            raise UseCaseError(Failure.CAPTURE_CLOSED)
        chunks = {chunk.seq: chunk for chunk in await self._repository.chunks(capture_id)}
        if not chunks:
            raise UseCaseError(Failure.EMPTY_CAPTURE)
        missing = tuple(seq for seq in range(last_seq + 1) if seq not in chunks)
        if missing:
            raise MissingChunksError(missing)
        key = f"recordings/{uuid4()}"
        try:
            with tempfile.TemporaryFile() as assembled:
                # MediaRecorder's slices of one stream play back as one file once joined in order.
                for seq in range(last_seq + 1):
                    assembled.write(await self._read(chunks[seq].storage_key))
                assembled.seek(0)
                await self._put(key, assembled)
            await self._recordings.attach_recording(
                user_id,
                capture.meeting_id,
                AssembledRecording(
                    key,
                    RecordingStatus.COMPLETE,
                    tuple(chunks[seq].storage_key for seq in sorted(chunks)),
                ),
                now,
            )
            await self._processing.queue_transcription(capture.meeting_id)
            await self._repository.close(capture_id, CaptureStatus.ASSEMBLED, last_seq, now)
        except BaseException:
            await asyncio.shield(self._discard(key))
            raise
        return await self._view(capture, CaptureStatus.ASSEMBLED)

    async def _own(self, user_id: UUID, capture_id: UUID, *, lock: bool) -> CaptureSession:
        capture = await self._repository.get(capture_id, lock=lock)
        if capture is None or capture.opened_by_user_id != user_id:
            raise UseCaseError(Failure.NOT_FOUND)
        await self._access.workspace_id(user_id, capture.meeting_id)
        return capture

    async def _view(self, capture: CaptureSession, status: CaptureStatus) -> CaptureView:
        chunks = await self._repository.chunks(capture.capture_session_id)
        return CaptureView(
            capture.capture_session_id,
            capture.meeting_id,
            status,
            tuple(chunk.seq for chunk in chunks),
        )

    async def _read(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self._storage.get, key)
        except ObjectStorageError:
            raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE) from None

    async def _put(self, key: str, data: BinaryIO) -> None:
        try:
            await asyncio.to_thread(
                self._storage.put, key, data, content_type="application/octet-stream"
            )
        except ObjectStorageError:
            raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE) from None

    async def _discard(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._storage.delete, key)
        except ObjectStorageError:
            logger.warning("An unused assembled recording was left for retention")
