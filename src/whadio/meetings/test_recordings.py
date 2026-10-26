import asyncio
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid4

import pytest

from ..shared.errors import Failure, UseCaseError
from ..shared.fakes import InMemoryObjectStorage
from .enums import ProcessingState
from .models import Meeting
from .recordings import RecordingObjects


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
    storage = InMemoryObjectStorage()
    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(
            RecordingObjects(storage).playback(
                RecordingAccess(deleted=deleted, deny=deny), uuid4(), uuid4()
            )
        )
    # Assert
    assert (failure.value.code, storage.presigned) == (expected, [])


def test_playback_link_expires_after_five_minutes() -> None:
    # Arrange
    storage = InMemoryObjectStorage()
    # Act
    asyncio.run(RecordingObjects(storage).playback(RecordingAccess(), uuid4(), uuid4()))
    # Assert
    assert storage.presigned == [("recording/test", timedelta(minutes=5))]


def test_failed_ingest_compensates_uploaded_object() -> None:
    # Arrange
    storage = InMemoryObjectStorage()
    recordings = RecordingObjects(storage)

    async def scenario() -> None:
        await recordings.put("new", BytesIO(b"audio"))
        # Act
        await recordings.rollback()

    asyncio.run(scenario())
    # Assert
    assert storage.objects == {}
