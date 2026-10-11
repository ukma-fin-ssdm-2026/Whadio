from collections.abc import Callable, Coroutine
from typing import Final, override

from fastapi import Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException
from starlette.types import Message

from ..core.errors import ApiError, ErrorCode

MAX_UPLOAD_BYTES: Final = 500 * 1024 * 1024
MAX_REQUEST_BYTES: Final = MAX_UPLOAD_BYTES + 1024 * 1024


class _RequestChunk(BaseModel):
    body: bytes = Field(default=b"", strict=True, description="ASGI request body chunk")


def _check_content_length(request: Request) -> None:
    values = request.headers.getlist("content-length")
    if not values:
        return
    value = values[0].strip(" \t")
    if len(values) != 1 or not value.isascii() or not value.isdecimal():
        raise ApiError(400, ErrorCode.MALFORMED_REQUEST, "Invalid Content-Length header")
    digits = value.lstrip("0") or "0"
    limit = str(MAX_REQUEST_BYTES)
    if len(digits) > len(limit) or (len(digits) == len(limit) and digits > limit):
        raise HTTPException(413, "The upload request exceeds the allowed size")


class RecordingUploadRoute(APIRoute):
    @override
    def get_route_handler(self) -> Callable[[Request], Coroutine[None, None, Response]]:
        handler = super().get_route_handler()
        if (
            self.methods is None
            or "POST" not in self.methods
            or not self.path.endswith("/workspaces/{workspace_id}/meetings")
        ):
            return handler

        async def limited_upload(request: Request) -> Response:
            _check_content_length(request)
            received = 0

            async def receive() -> Message:
                nonlocal received
                message = await request.receive()
                if message["type"] == "http.request":
                    received += len(_RequestChunk.model_validate(message).body)
                    if received > MAX_REQUEST_BYTES:
                        # HTTPException survives FastAPI's body-error translation; Starlette
                        # closes partially parsed upload files when the request stream fails.
                        raise HTTPException(413, "The upload request exceeds the allowed size")
                return message

            return await handler(Request(request.scope, receive=receive))

        return limited_upload
