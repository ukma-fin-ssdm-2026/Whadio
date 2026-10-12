import asyncio
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import BinaryIO
from uuid import UUID, uuid4

import pytest

from ..shared.errors import Failure, UseCaseError
from ..shared.storage import PresignedUrl
from .enums import ProcessingState
from .models import Meeting
from .recordings import RecordingObjects


class ObjectStore:
    def __init__(self) -> None:
        self.keys: list[str] = []
        self.signed: list[tuple[str, timedelta]] = []

    def put(self, key: str, data: BinaryIO, *, content_type: str) -> None:
        del data, content_type
        self.keys.append(key)

    def delete(self, key: str) -> None:
        self.keys.remove(key)

    def presign_get(self, key: str, *, expires_in: timedelta) -> PresignedUrl:
        self.signed.append((key, expires_in))
        return PresignedUrl("https://storage.test/playback", datetime.now(UTC) + expires_in)


class RecordingAccess:
    def __init__(self, *, deleted: bool = False, deny: bool = False) -> None:
        self.deleted: bool = deleted
        self.deny: bool = deny

    async def get(self, actor_id: UUID, meeting_id: UUID) -> Meeting:
        del actor_id, meeting_id
        if self.deny:
            raise UseCaseError(Failure.NOT_FOUND)
        return Meeting(
            storage_path="recording/test",
            processing_state=ProcessingState.PROCESSED,
            recording_deleted_at=datetime.now(UTC) if self.deleted else None,
        )


@pytest.mark.parametrize(
    ("deleted", "deny", "expected"),
    [
        (True, False, Failure.RECORDING_DELETED),
        (False, True, Failure.NOT_FOUND),
    ],
)
def test_unavailable_recording_produces_no_signed_link(
    *, deleted: bool, deny: bool, expected: Failure
) -> None:
    # Arrange
    storage = ObjectStore()
    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(
            RecordingObjects(storage).playback(
                RecordingAccess(deleted=deleted, deny=deny), uuid4(), uuid4()
            )
        )
    # Assert
    assert (failure.value.code, storage.signed) == (expected, [])


def test_playback_link_expires_after_five_minutes() -> None:
    # Arrange
    storage = ObjectStore()
    # Act
    asyncio.run(RecordingObjects(storage).playback(RecordingAccess(), uuid4(), uuid4()))
    # Assert
    assert storage.signed == [("recording/test", timedelta(minutes=5))]


def test_failed_ingest_compensates_uploaded_object() -> None:
    # Arrange
    storage = ObjectStore()
    recordings = RecordingObjects(storage)

    async def scenario() -> None:
        await recordings.put("new", BytesIO(b"audio"))
        # Act
        await recordings.rollback()

    asyncio.run(scenario())
    # Assert
    assert storage.keys == []
