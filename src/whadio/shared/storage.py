from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import BinaryIO, Final, Protocol

import urllib3
from minio import Minio
from minio.error import MinioException
from pydantic import BaseModel, Field, HttpUrl, SecretStr

MAX_PRESIGNED_LIFETIME: Final = timedelta(days=7)
_PART_SIZE: Final = 16 * 1024 * 1024


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


def _utc_now() -> datetime:
    return datetime.now(UTC)


class S3ObjectStorage:
    def __init__(
        self,
        client: Minio,
        signer: Minio,
        bucket: str,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._client: Minio = client
        self._signer: Minio = signer
        self._bucket: str = bucket
        self._now: Callable[[], datetime] = now

    def put(self, key: str, data: BinaryIO, *, content_type: str) -> None:
        try:
            self._client.put_object(
                self._bucket, key, data, length=-1, part_size=_PART_SIZE, content_type=content_type
            )
        except (MinioException, urllib3.exceptions.HTTPError) as error:
            raise ObjectStorageError("Storing an object failed") from error

    def delete(self, key: str) -> None:
        try:
            self._client.remove_object(self._bucket, key)
        except (MinioException, urllib3.exceptions.HTTPError) as error:
            raise ObjectStorageError("Deleting an object failed") from error

    def presign_get(self, key: str, *, expires_in: timedelta) -> PresignedUrl:
        if not timedelta(0) < expires_in <= MAX_PRESIGNED_LIFETIME:
            raise ValueError("a presigned URL lives longer than zero and at most 7 days")
        now = self._now()
        url = self._signer.presigned_get_object(
            self._bucket, key, expires=expires_in, request_date=now
        )
        return PresignedUrl(url=url, expires_at=now + expires_in)


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


def connect_s3_storage(settings: ObjectStorageSettings) -> S3ObjectStorage:
    # SigV4 signs the host, so a URL signed for the internal endpoint fails from outside it; the
    # signer only signs, for the public endpoint, and never connects.
    return S3ObjectStorage(
        client=create_s3_client(settings, settings.endpoint_url),
        signer=create_s3_client(settings, settings.public_endpoint_url or settings.endpoint_url),
        bucket=settings.bucket,
    )
