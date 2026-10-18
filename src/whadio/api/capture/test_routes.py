from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import BinaryIO, ClassVar, override
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...accounts.enums import NotesTemplate, WorkspaceRole
from ...accounts.models import Workspace, WorkspaceMembership
from ...meetings.enums import ProcessingState
from ...meetings.models import Folder, Meeting, RecordingDeletion
from ...meetings.processing import IMeetingProcessing
from ...meetings.repositories import MeetingRepository
from ...shared.storage import ObjectStorageSettings, S3ObjectStorage, connect_s3_storage
from ..app import create_app
from ..composition import (
    UnavailableMeetingProcessing,
    capture_storage,
    meeting_processing,
    transaction,
)
from ..core.errors import ErrorResponse
from ..core.schemas import Page
from .schemas import CaptureRead, DestinationRead

pytestmark = pytest.mark.slow

PASSWORD = uuid4().hex
# The header of a WebM stream as MediaRecorder starts it; the server checks only the part's type.
HEAD = b"\x1a\x45\xdf\xa3head"


class _StackSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_file=".env", extra="ignore")

    s3_access_key: SecretStr = Field(description="Access key of the Compose stack's SeaweedFS")
    s3_secret_key: SecretStr = Field(description="Secret key of the Compose stack's SeaweedFS")


class TrackedStorage:
    """The Compose stack's SeaweedFS, remembering what it stored so the test can remove it."""

    def __init__(self) -> None:
        stack = _StackSettings.model_validate({})
        self._storage: S3ObjectStorage = connect_s3_storage(
            ObjectStorageSettings(
                endpoint_url=HttpUrl("http://localhost:8333"),
                access_key=stack.s3_access_key,
                secret_key=stack.s3_secret_key,
            )
        )
        self.keys: list[str] = []

    def put(self, key: str, data: BinaryIO, *, content_type: str) -> None:
        self.keys.append(key)
        self._storage.put(key, data, content_type=content_type)

    def get(self, key: str) -> bytes:
        return self._storage.get(key)

    def delete(self, key: str) -> None:
        self._storage.delete(key)

    def remove_all(self) -> None:
        for key in self.keys:
            self._storage.delete(key)


@dataclass
class QueueSpy(UnavailableMeetingProcessing):
    queued: list[UUID] = field(default_factory=list)

    @override
    async def queue_transcription(self, meeting_id: UUID) -> None:
        self.queued.append(meeting_id)


@dataclass
class Recorder:
    client: AsyncClient
    session: AsyncSession
    storage: TrackedStorage
    queue: QueueSpy
    workspace_id: UUID

    async def start(self) -> CaptureRead:
        response = await self.client.post("/api/v1/captures", json={"consent_confirmed": True})
        return CaptureRead.model_validate_json(response.content)

    async def chunk(self, capture_id: UUID, seq: int, audio: bytes) -> int:
        response = await self.client.put(
            f"/api/v1/captures/{capture_id}/chunks/{seq}",
            files={"audio": ("chunk.webm", audio, "audio/webm;codecs=opus")},
            data={"speaker_events": '[{"at_seconds": 0.5, "speakers": ["Alice"]}]'},
        )
        return response.status_code


async def _personal_workspace(session: AsyncSession, user_id: UUID) -> UUID:
    workspace = Workspace(name="Personal", default_template=NotesTemplate.SUMMARY, is_personal=True)
    session.add(workspace)
    await session.flush()
    session.add(
        WorkspaceMembership(
            workspace_id=workspace.workspace_id, user_id=user_id, role=WorkspaceRole.OWNER
        )
    )
    session.add(Folder(workspace_id=workspace.workspace_id, name="General", is_default=True))
    await session.flush()
    return workspace.workspace_id


@asynccontextmanager
async def recorder(session: AsyncSession) -> AsyncGenerator[Recorder]:
    user = await AsyncDatabase.add_account(session, PASSWORD)
    workspace_id = await _personal_workspace(session, user.user_id)
    storage, queue = TrackedStorage(), QueueSpy()
    app = create_app()

    async def savepoint() -> AsyncGenerator[AsyncSession]:
        async with session.begin_nested():
            yield session

    def processing() -> IMeetingProcessing:
        return queue

    app.dependency_overrides[transaction] = savepoint
    app.dependency_overrides[capture_storage] = lambda: storage
    app.dependency_overrides[meeting_processing] = processing
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="https://example.test"
        ) as client:
            signed_in = await client.post(
                "/api/v1/sessions",
                json={"email": user.email, "password": PASSWORD, "kind": "extension"},
            )
            client.headers["Authorization"] = f"Bearer {signed_in.json()['token']}"
            yield Recorder(client, session, storage, queue, workspace_id)
    finally:
        storage.remove_all()


def run[T](async_database: AsyncDatabase, scenario: Callable[[Recorder], Awaitable[T]]) -> T:
    async def in_session(session: AsyncSession) -> T:
        async with recorder(session) as ready:
            return await scenario(ready)

    return async_database.run(in_session)


def test_extension_recording_becomes_one_stored_file(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(ready: Recorder) -> bool:
        capture = await ready.start()
        await ready.chunk(capture.id, 1, b"-tail")
        await ready.chunk(capture.id, 0, HEAD)
        # Act
        await ready.client.post(f"/api/v1/captures/{capture.id}/complete", json={"last_seq": 1})
        meeting = await ready.session.get(Meeting, capture.meeting_id, populate_existing=True)
        path = "" if meeting is None or meeting.storage_path is None else meeting.storage_path
        return ready.storage.get(path) == HEAD + b"-tail"

    joined = run(async_database, scenario)
    # Assert
    assert joined


def test_assembled_capture_queues_its_chunks_for_deletion(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(ready: Recorder) -> tuple[set[str], set[str]]:
        capture = await ready.start()
        await ready.chunk(capture.id, 0, HEAD)
        await ready.chunk(capture.id, 1, b"-tail")
        # Act
        await ready.client.post(f"/api/v1/captures/{capture.id}/complete", json={"last_seq": 1})
        pending = set(await ready.session.scalars(select(RecordingDeletion.storage_key)))
        return pending, {f"captures/{capture.id}/0", f"captures/{capture.id}/1"}

    pending, expected = run(async_database, scenario)
    # Assert
    assert pending == expected


def test_deleting_an_unfinished_capture_queues_its_chunks(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(ready: Recorder) -> tuple[list[str], list[str]]:
        capture = await ready.start()
        await ready.chunk(capture.id, 0, HEAD)
        # Act
        await MeetingRepository(ready.session).remove(capture.meeting_id, datetime.now(UTC))
        pending = list(await ready.session.scalars(select(RecordingDeletion.storage_key)))
        return pending, [f"captures/{capture.id}/0"]

    pending, expected = run(async_database, scenario)
    # Assert
    assert pending == expected


def test_capture_meeting_is_recording_in_the_personal_workspace(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(ready: Recorder) -> tuple[ProcessingState | None, UUID | None]:
        # Act
        capture = await ready.start()
        found = await ready.session.execute(
            select(Meeting.processing_state, Folder.workspace_id)
            .join(Folder, Folder.folder_id == Meeting.folder_id)
            .where(Meeting.meeting_id == capture.meeting_id)
        )
        row = found.one_or_none()
        return (None, None) if row is None else (row[0], row[1])

    state, workspace = run(async_database, scenario)
    # Assert
    assert (state, workspace is not None) == (ProcessingState.RECORDING, True)


def test_capture_meeting_stores_the_consent(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(ready: Recorder) -> bool:
        # Act
        capture = await ready.start()
        meeting = await ready.session.get(Meeting, capture.meeting_id)
        return meeting is not None and meeting.consent_confirmed_at is not None

    confirmed = run(async_database, scenario)
    # Assert
    assert confirmed


def test_capture_without_consent_is_invalid(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(ready: Recorder) -> int:
        # Act
        response = await ready.client.post("/api/v1/captures", json={"consent_confirmed": False})
        return response.status_code

    status = run(async_database, scenario)
    # Assert
    assert status == 422


def test_completed_capture_is_queued_once(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(ready: Recorder) -> list[UUID]:
        capture = await ready.start()
        await ready.chunk(capture.id, 0, HEAD)
        # Act
        for _ in range(2):
            await ready.client.post(f"/api/v1/captures/{capture.id}/complete", json={"last_seq": 0})
        return ready.queue.queued

    queued = run(async_database, scenario)
    # Assert
    assert len(queued) == 1


def test_repeated_chunk_is_acknowledged_with_200(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(ready: Recorder) -> tuple[int, int]:
        capture = await ready.start()
        # Act
        first = await ready.chunk(capture.id, 0, HEAD)
        again = await ready.chunk(capture.id, 0, HEAD)
        return first, again

    statuses = run(async_database, scenario)
    # Assert
    assert statuses == (201, 200)


def test_non_audio_chunk_is_refused_with_415(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(ready: Recorder) -> int:
        capture = await ready.start()
        # Act
        response = await ready.client.put(
            f"/api/v1/captures/{capture.id}/chunks/0",
            files={"audio": ("notes.txt", b"text", "text/plain")},
        )
        return response.status_code

    status = run(async_database, scenario)
    # Assert
    assert status == 415


def test_missing_chunks_are_named_in_the_details(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(ready: Recorder) -> list[str]:
        capture = await ready.start()
        await ready.chunk(capture.id, 0, HEAD)
        # Act
        response = await ready.client.post(
            f"/api/v1/captures/{capture.id}/complete", json={"last_seq": 2}
        )
        error = ErrorResponse.model_validate_json(response.content).error
        return [error.code, *(detail.message for detail in error.details)]

    found = run(async_database, scenario)
    # Assert
    assert found == ["MISSING_CHUNKS", "chunk 1 is missing", "chunk 2 is missing"]


def test_capture_resumes_from_the_chunks_received(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(ready: Recorder) -> list[int]:
        capture = await ready.start()
        await ready.chunk(capture.id, 0, HEAD)
        await ready.chunk(capture.id, 2, b"c")
        # Act
        response = await ready.client.get(f"/api/v1/captures/{capture.id}")
        return CaptureRead.model_validate_json(response.content).received_seqs

    received = run(async_database, scenario)
    # Assert
    assert received == [0, 2]


def test_destinations_include_the_personal_workspace(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(ready: Recorder) -> list[tuple[str, bool]]:
        # Act
        response = await ready.client.get("/api/v1/captures/destinations")
        page = Page[DestinationRead].model_validate_json(response.content)
        return [(item.name, item.is_personal) for item in page.items]

    found = run(async_database, scenario)
    # Assert
    assert found == [("Personal", True)]
