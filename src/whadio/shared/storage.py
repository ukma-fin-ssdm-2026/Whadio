import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import BinaryIO, Final, Protocol

import urllib3
from minio import Minio
from minio.error import MinioException, S3Error, ServerError
from pydantic import BaseModel, Field, HttpUrl, SecretStr

logger = logging.getLogger(__name__)

MIN_PRESIGNED_LIFETIME: Final = timedelta(seconds=1)
MAX_PRESIGNED_LIFETIME: Final = timedelta(days=7)
_PART_SIZE: Final = 16 * 1024 * 1024
_BACKOFF_BASE: Final = 0.25
_BACKOFF_CAP: Final = 2.0


class ObjectStorageSettings(BaseModel):
    endpoint_url: HttpUrl = Field(description="S3 API endpoint the backend connects to")
    public_endpoint_url: HttpUrl | None = Field(
        default=None,
        description="Endpoint presigned URLs are made for, as their users reach it; "
        "the backend endpoint when unset",
    )
    region: str = Field(default="us-east-1", description="Region requests are signed for")
    bucket: str = Field(default="recordings", min_length=3, description="Bucket of recordings")
    access_key: SecretStr = Field(description="Access key id")
    secret_key: SecretStr = Field(description="Secret access key")
    timeout: timedelta = Field(
        default=timedelta(seconds=5),
        gt=timedelta(0),
        description="Time a connection to storage, or a wait for its next bytes, may take",
    )
    attempts: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Tries a storage read or delete gets, the first included, before it fails",
    )


@dataclass(frozen=True, slots=True)
class PresignedUrl:
    url: str
    expires_at: datetime


class ObjectStorageError(Exception):
    pass


class IObjectStorage(Protocol):
    def put(self, key: str, data: BinaryIO, *, content_type: str) -> None: ...

    def delete(self, key: str) -> None: ...

    def presign_get(self, key: str, *, expires_in: timedelta) -> PresignedUrl: ...


def check_presigned_lifetime(expires_in: timedelta) -> None:
    # minio refuses a lifetime under 1 s and signs a fraction of a second truncated.
    if expires_in.microseconds or not (
        MIN_PRESIGNED_LIFETIME <= expires_in <= MAX_PRESIGNED_LIFETIME
    ):
        raise ValueError("a presigned URL lives whole seconds, from 1 second to 7 days")


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Backoff:
    attempts: int
    uniform: Callable[[float, float], float] = field(
        default_factory=lambda: random.SystemRandom().uniform
    )
    sleep: Callable[[float], None] = time.sleep

    def wait(self, retry: int) -> None:
        """Sleep before retry number `retry`, the first being 0."""
        self.sleep(self.uniform(0.0, min(_BACKOFF_CAP, _BACKOFF_BASE * 2.0**retry)))


def _is_transient(error: MinioException | urllib3.exceptions.HTTPError) -> bool:
    if isinstance(error, ServerError):
        return error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
    if isinstance(error, S3Error):
        return error.response.status >= HTTPStatus.INTERNAL_SERVER_ERROR
    return isinstance(error, urllib3.exceptions.HTTPError)


class S3ObjectStorage:
    def __init__(
        self,
        client: Minio,
        signer: Minio,
        bucket: str,
        backoff: Backoff,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._client: Minio = client
        self._signer: Minio = signer
        self._bucket: str = bucket
        self._backoff: Backoff = backoff
        self._now: Callable[[], datetime] = now

    def put(self, key: str, data: BinaryIO, *, content_type: str) -> None:
        try:
            self._client.put_object(
                self._bucket, key, data, length=-1, part_size=_PART_SIZE, content_type=content_type
            )
        except (MinioException, urllib3.exceptions.HTTPError) as error:
            raise ObjectStorageError("Storing an object failed") from error

    def get(self, key: str) -> bytes:
        return self._retried("Reading an object", lambda: self._read(key))

    def delete(self, key: str) -> None:
        self._retried("Deleting an object", lambda: self._client.remove_object(self._bucket, key))

    def presign_get(self, key: str, *, expires_in: timedelta) -> PresignedUrl:
        check_presigned_lifetime(expires_in)
        now = self._now()
        url = self._signer.presigned_get_object(
            self._bucket, key, expires=expires_in, request_date=now
        )
        return PresignedUrl(url=url, expires_at=now + expires_in)

    def _read(self, key: str) -> bytes:
        response = self._client.get_object(self._bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def _retried[T](self, operation: str, call: Callable[[], T]) -> T:
        attempt = 1
        while True:
            try:
                return call()
            except (MinioException, urllib3.exceptions.HTTPError) as error:
                if not _is_transient(error):
                    raise ObjectStorageError(f"{operation} failed") from error
                if attempt >= self._backoff.attempts:
                    logger.warning("%s failed after %d attempts", operation, attempt)
                    raise ObjectStorageError(f"{operation} failed") from error
            self._backoff.wait(attempt - 1)
            attempt += 1


def create_s3_client(
    settings: ObjectStorageSettings,
    endpoint_url: HttpUrl,
    http_client: urllib3.PoolManager | None = None,
) -> Minio:
    # With the region given, the client never asks the server where the bucket is, so presigning
    # sends no request.
    return Minio(
        f"{endpoint_url.host}:{endpoint_url.port}",
        access_key=settings.access_key.get_secret_value(),
        secret_key=settings.secret_key.get_secret_value(),
        secure=endpoint_url.scheme == "https",
        region=settings.region,
        http_client=http_client,
    )


def bounded_pool(settings: ObjectStorageSettings) -> urllib3.PoolManager:
    timeout = settings.timeout.total_seconds()
    # minio's own pool waits 300 s for each read and retries 5 times. `total=False` raises every
    # error to S3ObjectStorage instead, so retries happen at one level; the system CA store, which
    # honours SSL_CERT_FILE, replaces minio's certifi bundle.
    return urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=timeout, read=timeout),
        maxsize=10,
        cert_reqs="CERT_REQUIRED",
        retries=urllib3.Retry(total=False),
    )


def connect_s3_storage(
    settings: ObjectStorageSettings, *, sleep: Callable[[float], None] = time.sleep
) -> S3ObjectStorage:
    pool = bounded_pool(settings)
    # SigV4 signs the host, so a URL signed for the internal endpoint fails from outside it; the
    # signer only signs, for the public endpoint, and never connects.
    return S3ObjectStorage(
        client=create_s3_client(settings, settings.endpoint_url, pool),
        signer=create_s3_client(
            settings, settings.public_endpoint_url or settings.endpoint_url, pool
        ),
        bucket=settings.bucket,
        backoff=Backoff(settings.attempts, sleep=sleep),
    )
