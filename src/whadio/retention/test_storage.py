import asyncio
import threading

import pytest

from ..shared.fakes import InMemoryObjectStorage
from .services import StorageUnavailableError
from .storage import RecordingStorage


def test_recording_cleanup_runs_blocking_storage_call_outside_event_loop_thread() -> None:
    # Arrange
    store = InMemoryObjectStorage()
    adapter = RecordingStorage(store)
    loop_thread = threading.get_ident()
    # Act
    asyncio.run(adapter.delete("recording/test"))
    # Assert
    assert (store.deleted, loop_thread in store.caller_threads) == (["recording/test"], False)


def test_recording_cleanup_translates_storage_failure_without_exposing_key() -> None:
    # Arrange
    adapter = RecordingStorage(InMemoryObjectStorage(fail_delete=True))
    # Act
    with pytest.raises(StorageUnavailableError) as failure:
        asyncio.run(adapter.delete("private/recording"))
    # Assert
    assert str(failure.value) == "Recording cleanup failed"
