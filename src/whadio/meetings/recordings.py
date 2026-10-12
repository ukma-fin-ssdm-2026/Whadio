import asyncio
import logging
from datetime import timedelta
from typing import BinaryIO, Protocol
from uuid import UUID

from ..shared.errors import Failure, UseCaseError
from ..shared.storage import IObjectStorage, ObjectStorageError, PresignedUrl
from .enums import ProcessingState
from .models import Meeting

logger = logging.getLogger(__name__)


class IRecordingAccess(Protocol):
    async def get(self, actor_id: UUID, meeting_id: UUID) -> Meeting: ...


class RecordingObjects:
    def __init__(self, storage: IObjectStorage) -> None:
        self._storage: IObjectStorage = storage
        self._uploaded: list[str] = []

    async def put(self, key: str, data: BinaryIO) -> None:
        self._uploaded.append(key)
        try:
            await asyncio.to_thread(
                self._storage.put, key, data, content_type="application/octet-stream"
            )
        except ObjectStorageError:
            raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE) from None

    async def rollback(self) -> None:
        for key in self._uploaded:
            try:
                await asyncio.to_thread(self._storage.delete, key)
            except ObjectStorageError:
                logger.warning("Failed-upload object cleanup was deferred to retention")

    async def playback(
        self, meetings: IRecordingAccess, actor_id: UUID, meeting_id: UUID
    ) -> PresignedUrl:
        meeting = await meetings.get(actor_id, meeting_id)
        if meeting.recording_deleted_at is not None:
            raise UseCaseError(Failure.RECORDING_DELETED)
        if meeting.storage_path is None or meeting.processing_state == ProcessingState.RECORDING:
            raise UseCaseError(Failure.RECORDING_NOT_READY)
        try:
            return await asyncio.to_thread(
                self._storage.presign_get, meeting.storage_path, expires_in=timedelta(minutes=5)
            )
        except ObjectStorageError:
            raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE) from None
