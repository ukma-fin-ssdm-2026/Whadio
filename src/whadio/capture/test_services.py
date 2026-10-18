import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import BinaryIO
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue

from ..accounts.enums import NotesTemplate, WorkspaceRole
from ..accounts.repositories import MemberWorkspace
from ..meetings.enums import RecordingStatus
from ..meetings.models import Folder, Meeting
from ..meetings.services import RecordingInput
from ..shared.errors import Failure, UseCaseError
from ..shared.storage import ObjectStorageError
from .enums import CaptureStatus
from .models import CaptureChunk, CaptureSession
from .services import (
    CaptureCollaborators,
    CaptureService,
    CaptureView,
    ChunkUpload,
    MissingChunksError,
    SpeakerEvent,
)

NOW = datetime(2026, 10, 18, 18, 0, tzinfo=UTC)
USER = uuid4()
PERSONAL = uuid4()
TEAM = uuid4()


class FakeRepository:
    def __init__(self) -> None:
        self.captures: dict[UUID, CaptureSession] = {}
        self.stored: list[CaptureChunk] = []

    async def open(self, meeting_id: UUID, user_id: UUID, now: datetime, /) -> CaptureSession:
        capture = CaptureSession(
            capture_session_id=uuid4(),
            meeting_id=meeting_id,
            opened_by_user_id=user_id,
            status=CaptureStatus.RECORDING,
            created_at=now,
        )
        self.captures[capture.capture_session_id] = capture
        return capture

    async def get(self, capture_id: UUID, /, *, lock: bool = False) -> CaptureSession | None:
        del lock
        return self.captures.get(capture_id)

    async def chunks(self, capture_id: UUID, /) -> list[CaptureChunk]:
        return sorted(
            (chunk for chunk in self.stored if chunk.capture_session_id == capture_id),
            key=lambda chunk: chunk.seq,
        )

    async def chunk(self, capture_id: UUID, seq: int, /) -> CaptureChunk | None:
        return next(
            (
                chunk
                for chunk in self.stored
                if chunk.capture_session_id == capture_id and chunk.seq == seq
            ),
            None,
        )

    async def add_chunk(
        self,
        capture_id: UUID,
        seq: int,
        storage_key: str,
        speaker_events: JsonValue,
        now: datetime,
        /,
    ) -> None:
        self.stored.append(
            CaptureChunk(
                capture_session_id=capture_id,
                seq=seq,
                storage_key=storage_key,
                speaker_events=speaker_events,
                received_at=now,
            )
        )

    async def close(
        self, capture_id: UUID, status: CaptureStatus, last_seq: int, now: datetime, /
    ) -> None:
        capture = self.captures[capture_id]
        capture.status = status
        capture.last_chunk_seq = last_seq
        capture.closed_at = now


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.unavailable: bool = False

    def put(self, key: str, data: BinaryIO, *, content_type: str) -> None:
        del content_type
        if self.unavailable:
            raise ObjectStorageError("down")
        self.objects[key] = data.read()

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class FakeWorkspaces:
    async def list_workspaces(self, user_id: UUID, /) -> list[MemberWorkspace]:
        del user_id
        return [
            MemberWorkspace(
                workspace_id,
                name,
                workspace_id == PERSONAL,
                WorkspaceRole.OWNER,
                1,
                NotesTemplate.SUMMARY,
                NOW,
            )
            for workspace_id, name in ((TEAM, "Team"), (PERSONAL, "Personal"))
        ]


class FakeFolders:
    async def folders(self, actor_id: UUID, workspace_id: UUID, /) -> list[Folder]:
        del actor_id
        return [Folder(folder_id=uuid4(), workspace_id=workspace_id, name="General")]


@dataclass
class FakeMeetings:
    ingested: list[tuple[UUID, RecordingInput]] = field(default_factory=list)
    attached: list[tuple[UUID, str, RecordingStatus]] = field(default_factory=list)

    async def ingest(
        self, actor_id: UUID, workspace_id: UUID, recording: RecordingInput, now: datetime, /
    ) -> Meeting:
        del actor_id, now
        self.ingested.append((workspace_id, recording))
        return Meeting(meeting_id=uuid4())

    async def attach_recording(
        self, meeting_id: UUID, storage_key: str, status: RecordingStatus, /
    ) -> None:
        self.attached.append((meeting_id, storage_key, status))


@dataclass
class FakeQueue:
    queued: list[UUID] = field(default_factory=list)
    unavailable: bool = False

    async def queue_transcription(self, meeting_id: UUID, /) -> None:
        if self.unavailable:
            raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)
        self.queued.append(meeting_id)


@dataclass
class Fixture:
    service: CaptureService
    repository: FakeRepository
    storage: FakeStorage
    meetings: FakeMeetings
    queue: FakeQueue


def fixture() -> Fixture:
    repository, storage, meetings, queue = (
        FakeRepository(),
        FakeStorage(),
        FakeMeetings(),
        FakeQueue(),
    )
    service = CaptureService(
        CaptureCollaborators(
            repository, storage, FakeWorkspaces(), FakeFolders(), meetings, meetings, queue
        )
    )
    return Fixture(service, repository, storage, meetings, queue)


def started(setup: Fixture) -> CaptureView:
    return asyncio.run(setup.service.start(USER, TEAM, None, consent_confirmed=True, now=NOW))


def upload(setup: Fixture, capture_id: UUID, seq: int, audio: bytes, user: UUID = USER) -> bool:
    return asyncio.run(
        setup.service.put_chunk(
            user,
            capture_id,
            ChunkUpload(seq, audio, (SpeakerEvent(1.5, ("Alice",)),)),
            NOW,
        )
    )


def complete(setup: Fixture, capture_id: UUID, last_seq: int) -> CaptureView:
    return asyncio.run(setup.service.complete(USER, capture_id, last_seq, NOW))


# --- Starting ---


def test_capture_without_consent_is_refused() -> None:
    # Arrange
    setup = fixture()

    # Act
    with pytest.raises(UseCaseError) as error:
        asyncio.run(setup.service.start(USER, TEAM, None, consent_confirmed=False, now=NOW))

    # Assert
    assert error.value.code == Failure.VALIDATION_ERROR


def test_capture_without_destination_goes_to_the_personal_workspace() -> None:
    # Arrange
    setup = fixture()

    # Act
    asyncio.run(setup.service.start(USER, None, None, consent_confirmed=True, now=NOW))

    # Assert
    assert setup.meetings.ingested[0][0] == PERSONAL


def test_folder_without_workspace_is_refused() -> None:
    # Arrange
    setup = fixture()

    # Act
    with pytest.raises(UseCaseError) as error:
        asyncio.run(setup.service.start(USER, None, uuid4(), consent_confirmed=True, now=NOW))

    # Assert
    assert error.value.code == Failure.VALIDATION_ERROR


def test_capture_creates_an_extension_meeting_without_a_recording_yet() -> None:
    # Arrange
    setup = fixture()

    # Act
    started(setup)

    # Assert
    recording = setup.meetings.ingested[0][1]
    assert (recording.storage_key, recording.consent_confirmed_at) == (None, NOW)


def test_new_capture_is_recording_with_no_chunks() -> None:
    # Arrange
    setup = fixture()

    # Act
    view = started(setup)

    # Assert
    assert (view.status, view.received_seqs) == (CaptureStatus.RECORDING, ())


def test_destinations_list_each_workspace_with_its_folders() -> None:
    # Arrange
    setup = fixture()

    # Act
    found = asyncio.run(setup.service.destinations(USER))

    # Assert
    assert [(item.workspace.name, len(item.folders)) for item in found] == [
        ("Team", 1),
        ("Personal", 1),
    ]


# --- Chunks ---


def test_new_chunk_is_stored() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id

    # Act
    created = upload(setup, capture_id, 0, b"head")

    # Assert
    assert (created, setup.storage.objects) == (True, {f"captures/{capture_id}/0": b"head"})


def test_chunk_keeps_its_speaker_events() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id

    # Act
    upload(setup, capture_id, 0, b"head")

    # Assert
    assert setup.repository.stored[0].speaker_events == [{"at_seconds": 1.5, "speakers": ["Alice"]}]


def test_same_chunk_again_changes_nothing() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id
    upload(setup, capture_id, 0, b"head")

    # Act
    created = upload(setup, capture_id, 0, b"head")

    # Assert
    assert (created, len(setup.repository.stored)) == (False, 1)


def test_different_audio_under_a_stored_number_is_refused() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id
    upload(setup, capture_id, 0, b"head")

    # Act
    with pytest.raises(UseCaseError) as error:
        upload(setup, capture_id, 0, b"other")

    # Assert
    assert error.value.code == Failure.CHUNK_MISMATCH


def test_empty_chunk_is_refused() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id

    # Act
    with pytest.raises(UseCaseError) as error:
        upload(setup, capture_id, 0, b"")

    # Assert
    assert error.value.code == Failure.VALIDATION_ERROR


def test_another_accounts_capture_is_missing() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id

    # Act
    with pytest.raises(UseCaseError) as error:
        upload(setup, capture_id, 0, b"head", user=uuid4())

    # Assert
    assert error.value.code == Failure.NOT_FOUND


def test_chunk_after_completion_is_refused() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id
    upload(setup, capture_id, 0, b"head")
    complete(setup, capture_id, 0)

    # Act
    with pytest.raises(UseCaseError) as error:
        upload(setup, capture_id, 1, b"late")

    # Assert
    assert error.value.code == Failure.CAPTURE_CLOSED


def test_unavailable_storage_stores_no_chunk() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id
    setup.storage.unavailable = True

    # Act
    with pytest.raises(UseCaseError):
        upload(setup, capture_id, 0, b"head")

    # Assert
    assert setup.repository.stored == []


def test_capture_lists_the_chunks_received() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id
    upload(setup, capture_id, 2, b"c")
    upload(setup, capture_id, 0, b"a")

    # Act
    view = asyncio.run(setup.service.get(USER, capture_id))

    # Assert
    assert view.received_seqs == (0, 2)


# --- Completing ---


def test_completion_joins_the_chunks_in_order() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id
    upload(setup, capture_id, 1, b"-tail")
    upload(setup, capture_id, 0, b"head")

    # Act
    complete(setup, capture_id, 1)

    # Assert
    assert setup.storage.objects[setup.meetings.attached[0][1]] == b"head-tail"


def test_completion_queues_the_meeting_for_transcription() -> None:
    # Arrange
    setup = fixture()
    view = started(setup)
    upload(setup, view.capture_id, 0, b"head")

    # Act
    complete(setup, view.capture_id, 0)

    # Assert
    assert setup.queue.queued == [view.meeting_id]


def test_completed_capture_is_assembled() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id
    upload(setup, capture_id, 0, b"head")

    # Act
    view = complete(setup, capture_id, 0)

    # Assert
    assert view.status == CaptureStatus.ASSEMBLED


def test_completion_with_a_gap_names_the_missing_chunks() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id
    upload(setup, capture_id, 0, b"a")
    upload(setup, capture_id, 3, b"d")

    # Act
    with pytest.raises(MissingChunksError) as error:
        complete(setup, capture_id, 3)

    # Assert
    assert error.value.missing == (1, 2)


def test_completion_without_chunks_is_refused() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id

    # Act
    with pytest.raises(UseCaseError) as error:
        complete(setup, capture_id, 0)

    # Assert
    assert error.value.code == Failure.EMPTY_CAPTURE


def test_repeated_completion_queues_once() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id
    upload(setup, capture_id, 0, b"head")
    complete(setup, capture_id, 0)

    # Act
    complete(setup, capture_id, 0)

    # Assert
    assert len(setup.queue.queued) == 1


def test_completion_with_another_last_chunk_after_assembly_is_refused() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id
    upload(setup, capture_id, 0, b"head")
    complete(setup, capture_id, 0)

    # Act
    with pytest.raises(UseCaseError) as error:
        complete(setup, capture_id, 1)

    # Assert
    assert error.value.code == Failure.CAPTURE_CLOSED


def test_failed_queueing_leaves_no_assembled_recording() -> None:
    # Arrange
    setup = fixture()
    capture_id = started(setup).capture_id
    upload(setup, capture_id, 0, b"head")
    setup.queue.unavailable = True

    # Act
    with pytest.raises(UseCaseError):
        complete(setup, capture_id, 0)

    # Assert
    assert list(setup.storage.objects) == [f"captures/{capture_id}/0"]
