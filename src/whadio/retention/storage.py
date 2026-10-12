import asyncio

from ..shared.storage import IObjectStorage, ObjectStorageError
from .services import StorageUnavailableError


class RecordingStorage:
    def __init__(self, storage: IObjectStorage) -> None:
        self._storage: IObjectStorage = storage

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._storage.delete, key)
        except ObjectStorageError:
            raise StorageUnavailableError("Recording cleanup failed") from None
