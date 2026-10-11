import asyncio
from collections.abc import AsyncIterator
from contextlib import ExitStack
from tempfile import SpooledTemporaryFile
from typing import Annotated, override
from uuid import UUID

import pytest
from fastapi import APIRouter, FastAPI, File, UploadFile
from httpx import ASGITransport, AsyncByteStream, AsyncClient, Response
from starlette import formparsers

from ..app import create_app
from ..core.errors import ErrorCode, ErrorResponse, register_error_handlers
from . import upload_limits
from .upload_limits import MAX_REQUEST_BYTES, RecordingUploadRoute

_PATH = "/api/v1/workspaces/00000000-0000-0000-0000-000000000001/meetings"
_PREFIX = (
    b"--boundary\r\n"
    b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
    b"Content-Type: application/octet-stream\r\n\r\n"
)
_SUFFIX = b"\r\n--boundary--\r\n"
_CONTENT_TYPE = ("Content-Type", "multipart/form-data; boundary=boundary")


class BodyStream(AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks: tuple[bytes, ...] = chunks
        self.reads: int = 0

    @override
    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.reads += 1
            yield chunk


class UploadProbe:
    def __init__(self) -> None:
        self.app: FastAPI = FastAPI()
        self.calls: int = 0
        router = APIRouter(route_class=RecordingUploadRoute)

        async def upload(
            workspace_id: UUID, file: Annotated[UploadFile, File(description="Recording")]
        ) -> int:
            del workspace_id
            self.calls += 1
            return len(await file.read())

        router.add_api_route("/workspaces/{workspace_id}/meetings", upload, methods=["POST"])
        router.add_api_route("/workspaces/{workspace_id}/other", upload, methods=["POST"])
        self.app.include_router(router, prefix="/api/v1")
        register_error_handlers(self.app)


async def post(
    app: FastAPI, stream: BodyStream, headers: list[tuple[str, str]], *, path: str = _PATH
) -> Response:
    async with AsyncClient(transport=ASGITransport(app), base_url="https://example.test") as client:
        return await client.post(path, content=stream, headers=headers)


def test_production_upload_rejects_declared_oversize_without_reading_body() -> None:
    # Arrange
    app = create_app()
    stream = BodyStream((_PREFIX, b"unread"))
    # Act
    response = asyncio.run(
        post(app, stream, [_CONTENT_TYPE, ("Content-Length", str(MAX_REQUEST_BYTES + 1))])
    )
    error = ErrorResponse.model_validate_json(response.content).error
    # Assert
    assert (response.status_code, error.code, error.request_id, stream.reads) == (
        413,
        ErrorCode.PAYLOAD_TOO_LARGE,
        response.headers["X-Request-ID"],
        0,
    )


@pytest.mark.parametrize("value", ["-1", "invalid", "1, 1", ""])
def test_invalid_content_length_is_rejected_without_reading_body(value: str) -> None:
    # Arrange
    probe = UploadProbe()
    stream = BodyStream((_PREFIX,))
    # Act
    response = asyncio.run(post(probe.app, stream, [_CONTENT_TYPE, ("Content-Length", value)]))
    error = ErrorResponse.model_validate_json(response.content).error
    # Assert
    assert (response.status_code, error.code, stream.reads, probe.calls) == (
        400,
        ErrorCode.MALFORMED_REQUEST,
        0,
        0,
    )


def test_duplicate_content_lengths_are_rejected_without_reading_body() -> None:
    # Arrange
    probe = UploadProbe()
    stream = BodyStream((_PREFIX,))
    # Act
    response = asyncio.run(
        post(probe.app, stream, [_CONTENT_TYPE, ("Content-Length", "1"), ("Content-Length", "2")])
    )
    # Assert
    assert (response.status_code, stream.reads, probe.calls) == (400, 0, 0)


def test_very_long_numeric_content_length_is_rejected_without_integer_conversion() -> None:
    # Arrange
    probe = UploadProbe()
    stream = BodyStream((_PREFIX,))
    # Act
    response = asyncio.run(post(probe.app, stream, [_CONTENT_TYPE, ("Content-Length", "9" * 5000)]))
    # Assert
    assert (response.status_code, stream.reads, probe.calls) == (413, 0, 0)


@pytest.mark.parametrize("length", [None, "1", "0001"])
def test_streamed_oversize_stops_reading_and_never_calls_upload(
    monkeypatch: pytest.MonkeyPatch, length: str | None
) -> None:
    # Arrange
    probe = UploadProbe()
    stream = BodyStream((_PREFIX + b"a", b"oversize", b"unread" + _SUFFIX))
    monkeypatch.setattr(upload_limits, "MAX_REQUEST_BYTES", len(_PREFIX) + 1)
    headers: list[tuple[str, str]] = [_CONTENT_TYPE]
    if length is not None:
        headers.append(("Content-Length", length))
    # Act
    response = asyncio.run(post(probe.app, stream, headers))
    error = ErrorResponse.model_validate_json(response.content).error
    # Assert
    assert (response.status_code, error.code, stream.reads, probe.calls) == (
        413,
        ErrorCode.PAYLOAD_TOO_LARGE,
        2,
        0,
    )


def test_streamed_oversize_closes_partial_spooled_files(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    probe = UploadProbe()
    files: list[SpooledTemporaryFile[bytes]] = []

    with ExitStack() as stack:

        def temporary_file(*, max_size: int) -> SpooledTemporaryFile[bytes]:
            file = stack.enter_context(SpooledTemporaryFile(max_size=max_size, mode="w+b"))
            files.append(file)
            return file

        monkeypatch.setattr(formparsers, "SpooledTemporaryFile", temporary_file)
        monkeypatch.setattr(formparsers.MultiPartParser, "spool_max_size", 4)
        monkeypatch.setattr(upload_limits, "MAX_REQUEST_BYTES", len(_PREFIX) + 8)
        stream = BodyStream((_PREFIX + b"12345678", b"oversize" + _SUFFIX))
        # Act
        response = asyncio.run(post(probe.app, stream, [_CONTENT_TYPE]))
        # Assert
        assert (response.status_code, len(files), [file.closed for file in files], probe.calls) == (
            413,
            1,
            [True],
            0,
        )


@pytest.mark.parametrize("length", [None, "accurate", "padded"])
def test_upload_at_request_limit_is_accepted(
    monkeypatch: pytest.MonkeyPatch, length: str | None
) -> None:
    # Arrange
    probe = UploadProbe()
    body = _PREFIX + b"audio" + _SUFFIX
    monkeypatch.setattr(upload_limits, "MAX_REQUEST_BYTES", len(body))
    stream = BodyStream((body[: len(_PREFIX)], body[len(_PREFIX) :]))
    headers: list[tuple[str, str]] = [_CONTENT_TYPE]
    if length is not None:
        headers.append(("Content-Length", ("000" if length == "padded" else "") + str(len(body))))
    # Act
    response = asyncio.run(post(probe.app, stream, headers))
    # Assert
    assert (response.status_code, response.json(), probe.calls) == (200, 5, 1)


def test_non_upload_routes_keep_existing_body_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    probe = UploadProbe()
    monkeypatch.setattr(upload_limits, "MAX_REQUEST_BYTES", 1)
    stream = BodyStream((_PREFIX + b"audio" + _SUFFIX,))
    # Act
    response = asyncio.run(
        post(probe.app, stream, [_CONTENT_TYPE], path=_PATH.removesuffix("meetings") + "other")
    )
    # Assert
    assert (response.status_code, response.json(), probe.calls) == (200, 5, 1)


def test_malformed_multipart_keeps_its_original_error() -> None:
    # Arrange
    probe = UploadProbe()
    stream = BodyStream((b"invalid",))
    # Act
    response = asyncio.run(post(probe.app, stream, [("Content-Type", "multipart/form-data")]))
    error = ErrorResponse.model_validate_json(response.content).error
    # Assert
    assert (response.status_code, error.code, probe.calls) == (400, ErrorCode.HTTP_ERROR, 0)
