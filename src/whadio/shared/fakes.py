import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import BinaryIO, override

from .storage import MAX_PRESIGNED_LIFETIME, IObjectStorage, ObjectStorageError, PresignedUrl


class FixedClock:
    def __init__(self, at: datetime) -> None:
        if at.utcoffset() != timedelta(0):
            raise ValueError("a fixed clock needs an aware UTC time")
        self._at: datetime = at

    def __call__(self) -> datetime:
        return self._at

    def advance(self, delta: timedelta) -> None:
        self._at += delta


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InMemoryObjectStorage(IObjectStorage):
    def __init__(
        self,
        *,
        base_url: str = "http://storage.test/recordings",
        now: Callable[[], datetime] = _utc_now,
        fail_put: bool = False,
        fail_delete: bool = False,
    ) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploaded: list[str] = []
        self.deleted: list[str] = []
        self.presigned: list[tuple[str, timedelta]] = []
        self.caller_threads: set[int] = set()
        self.fail_put: bool = fail_put
        self.fail_delete: bool = fail_delete
        self._base_url: str = base_url
        self._now: Callable[[], datetime] = now

    @override
    def put(self, key: str, data: BinaryIO, *, content_type: str) -> None:
        del content_type
        self.caller_threads.add(threading.get_ident())
        if self.fail_put:
            raise ObjectStorageError(f"Storing {key} failed")
        self.objects[key] = data.read()
        self.uploaded.append(key)

    @override
    def delete(self, key: str) -> None:
        self.caller_threads.add(threading.get_ident())
        if self.fail_delete:
            # Names the key so that tests can check a caller never passes it on.
            raise ObjectStorageError(f"Deleting {key} failed")
        self.objects.pop(key, None)
        self.deleted.append(key)

    @override
    def presign_get(self, key: str, *, expires_in: timedelta) -> PresignedUrl:
        self.caller_threads.add(threading.get_ident())
        if not timedelta(0) < expires_in <= MAX_PRESIGNED_LIFETIME:
            raise ValueError("a presigned URL lives longer than zero and at most 7 days")
        self.presigned.append((key, expires_in))
        return PresignedUrl(url=f"{self._base_url}/{key}", expires_at=self._now() + expires_in)
