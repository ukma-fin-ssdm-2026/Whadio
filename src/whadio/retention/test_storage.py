import asyncio
import threading
from datetime import timedelta
from typing import BinaryIO

import pytest

from ..shared.storage import ObjectStorageError, PresignedUrl
from .services import StorageUnavailableError
from .storage import RecordingStorage


class Store:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable: bool = unavailable
        self.deleted: list[str] = []
        self.thread_id: int | None = None

    def put(self, key: str, data: BinaryIO, *, content_type: str) -> None:
        del key, data, content_type
        raise AssertionError("Retention must not upload recordings")

    def presign_get(self, key: str, *, expires_in: timedelta) -> PresignedUrl:
        del key, expires_in
        raise AssertionError("Retention must not expose recordings")

    def delete(self, key: str) -> None:
        if self.unavailable:
            raise ObjectStorageError(f"Private storage path: {key}")
        self.thread_id = threading.get_ident()
        self.deleted.append(key)


def test_recording_cleanup_runs_blocking_storage_call_outside_event_loop_thread() -> None:
    # Arrange
    store = Store()
    adapter = RecordingStorage(store)
    loop_thread = threading.get_ident()
    # Act
    asyncio.run(adapter.delete("recording/test"))
    # Assert
    assert (store.deleted, store.thread_id != loop_thread) == (["recording/test"], True)


def test_recording_cleanup_translates_storage_failure_without_exposing_key() -> None:
    # Arrange
    adapter = RecordingStorage(Store(unavailable=True))
    # Act
    with pytest.raises(StorageUnavailableError) as failure:
        asyncio.run(adapter.delete("private/recording"))
    # Assert
    assert str(failure.value) == "Recording cleanup failed"
