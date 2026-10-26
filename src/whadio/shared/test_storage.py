import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import override
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import urllib3
from pydantic import HttpUrl, SecretStr

from conftest import refused_fields

from .storage import (
    ObjectStorageError,
    ObjectStorageSettings,
    S3ObjectStorage,
    connect_s3_storage,
    create_s3_client,
)

_KEY = "recordings/5d1f0c2a-9b8e-4f7d-a6c5-b4d3e2f1a0b9"
_NOW = datetime(2026, 10, 9, 18, tzinfo=UTC)
_SETTINGS = ObjectStorageSettings(
    endpoint_url=HttpUrl("http://seaweedfs:8333"),
    public_endpoint_url=HttpUrl("http://localhost:8333"),
    access_key=SecretStr("whadio-test"),
    secret_key=SecretStr("whadio-test-secret"),
)


@dataclass(frozen=True)
class _Request:
    method: str
    path: str
    content_type: str | None


class _FakeServer(urllib3.PoolManager):
    def __init__(self, status: int) -> None:
        super().__init__()
        self.requests: list[_Request] = []
        self._status: int = status

    @override
    def urlopen(
        self, method: str, url: str, redirect: bool = True, **kw: object
    ) -> urllib3.BaseHTTPResponse:
        headers = kw.get("headers")
        content_type = (
            headers.get("Content-Type") if isinstance(headers, urllib3.HTTPHeaderDict) else None
        )
        self.requests.append(_Request(method, urlsplit(url).path, content_type))
        return urllib3.HTTPResponse(body=b"", status=self._status, preload_content=True)


def _storage_on(server: _FakeServer) -> S3ObjectStorage:
    client = create_s3_client(_SETTINGS, _SETTINGS.endpoint_url, http_client=server)
    return S3ObjectStorage(client=client, signer=client, bucket=_SETTINGS.bucket)


def test_presigned_url_is_made_for_the_public_endpoint() -> None:
    # Arrange
    storage = connect_s3_storage(_SETTINGS)

    # Act
    presigned = storage.presign_get(_KEY, expires_in=timedelta(hours=1))

    # Assert
    assert urlsplit(presigned.url).netloc == "localhost:8333"


def test_presigned_url_names_the_bucket_in_its_path() -> None:
    # Arrange
    storage = connect_s3_storage(_SETTINGS)

    # Act
    presigned = storage.presign_get(_KEY, expires_in=timedelta(hours=1))

    # Assert
    assert urlsplit(presigned.url).path == f"/recordings/{_KEY}"


def test_presigned_url_carries_the_requested_lifetime() -> None:
    # Arrange
    storage = connect_s3_storage(_SETTINGS)

    # Act
    presigned = storage.presign_get(_KEY, expires_in=timedelta(minutes=30))

    # Assert
    assert parse_qs(urlsplit(presigned.url).query)["X-Amz-Expires"] == ["1800"]


def test_presigned_url_reports_when_it_expires() -> None:
    # Arrange
    client = create_s3_client(_SETTINGS, _SETTINGS.endpoint_url)
    storage = S3ObjectStorage(client=client, signer=client, bucket="recordings", now=lambda: _NOW)

    # Act
    presigned = storage.presign_get(_KEY, expires_in=timedelta(hours=2))

    # Assert
    assert presigned.expires_at == _NOW + timedelta(hours=2)


@pytest.mark.parametrize(
    ("lifetime", "expires"),
    [
        pytest.param(timedelta(seconds=1), "1", id="bva-min"),
        pytest.param(timedelta(seconds=2), "2", id="bva-above-min"),
        pytest.param(timedelta(days=7, seconds=-1), "604799", id="bva-below-max"),
        pytest.param(timedelta(days=7), "604800", id="bva-max"),
    ],
)
def test_presigned_url_lives_from_one_second_to_seven_days(
    lifetime: timedelta, expires: str
) -> None:
    # Arrange
    storage = connect_s3_storage(_SETTINGS)

    # Act
    presigned = storage.presign_get(_KEY, expires_in=lifetime)

    # Assert
    assert parse_qs(urlsplit(presigned.url).query)["X-Amz-Expires"] == [expires]


@pytest.mark.parametrize(
    "lifetime",
    [
        pytest.param(timedelta(0), id="bva-below-min"),
        pytest.param(timedelta(milliseconds=999), id="bva-below-min-by-a-fraction"),
        pytest.param(timedelta(days=7, seconds=1), id="bva-above-max"),
    ],
)
def test_presigning_refuses_a_lifetime_outside_one_second_to_seven_days(
    lifetime: timedelta,
) -> None:
    # Arrange
    storage = connect_s3_storage(_SETTINGS)

    # Act / Assert
    with pytest.raises(ValueError, match="presigned URL lives whole seconds"):
        storage.presign_get(_KEY, expires_in=lifetime)


def test_presigning_refuses_a_lifetime_with_a_fraction_of_a_second() -> None:
    # Arrange
    storage = connect_s3_storage(_SETTINGS)

    # Act / Assert
    with pytest.raises(ValueError, match="presigned URL lives whole seconds"):
        storage.presign_get(_KEY, expires_in=timedelta(seconds=1.5))


def test_put_stores_the_object_with_its_content_type_in_one_request() -> None:
    # Arrange
    server = _FakeServer(status=200)

    # Act
    _storage_on(server).put(_KEY, io.BytesIO(b"\x00\x00\x00\x18ftyp"), content_type="audio/mp4")

    # Assert
    assert server.requests == [_Request("PUT", f"/recordings/{_KEY}", "audio/mp4")]


def test_put_reports_a_refused_request_as_a_storage_error() -> None:
    # Arrange
    storage = _storage_on(_FakeServer(status=403))

    # Act / Assert
    with pytest.raises(ObjectStorageError, match="Storing an object failed"):
        storage.put(_KEY, io.BytesIO(b"data"), content_type="audio/mp4")


def test_delete_removes_the_object() -> None:
    # Arrange
    server = _FakeServer(status=204)

    # Act
    _storage_on(server).delete(_KEY)

    # Assert
    assert server.requests == [_Request("DELETE", f"/recordings/{_KEY}", None)]


def test_delete_reports_a_refused_request_as_a_storage_error() -> None:
    # Arrange
    storage = _storage_on(_FakeServer(status=500))

    # Act / Assert
    with pytest.raises(ObjectStorageError, match="Deleting an object failed"):
        storage.delete(_KEY)


@pytest.mark.parametrize(
    ("length", "refused"),
    [
        pytest.param(2, {"bucket"}, id="bva-below-min"),
        pytest.param(3, set[str](), id="bva-min"),
        pytest.param(4, set[str](), id="bva-above-min"),
    ],
)
def test_bucket_name_needs_at_least_3_characters(length: int, refused: set[str]) -> None:
    # Arrange
    data = {
        "endpoint_url": "http://seaweedfs:8333",
        "access_key": "whadio-test",
        "secret_key": uuid4().hex,
        "bucket": "b" * length,
    }

    # Act
    found = refused_fields(ObjectStorageSettings, data)

    # Assert
    assert found == refused
