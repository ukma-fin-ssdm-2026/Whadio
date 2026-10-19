import asyncio
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Annotated, Final, override

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.types import Message

from ...shared.telemetry import Observation
from ..composition import Observations
from ..core.errors import ApiError, ErrorCode, error_responses
from ..core.schemas import Input

MAX_OBSERVATION_BYTES: Final = 16384


class BoundedObservationRoute(APIRoute):
    @override
    def get_route_handler(self) -> Callable[[Request], Coroutine[None, None, Response]]:
        handler = super().get_route_handler()

        async def bounded(request: Request) -> Response:
            body = bytearray()
            try:
                async with asyncio.timeout(2):
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > MAX_OBSERVATION_BYTES:
                            raise ApiError(
                                413, ErrorCode.PAYLOAD_TOO_LARGE, "Observation exceeds 16 KiB"
                            )
                        body.extend(chunk)
            except TimeoutError:
                raise ApiError(
                    413, ErrorCode.PAYLOAD_TOO_LARGE, "Observation body timed out"
                ) from None

            async def receive() -> Message:
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            return await handler(Request(request.scope, receive))

        return bounded


router = APIRouter(tags=["admin"], route_class=BoundedObservationRoute)
collector_token = HTTPBearer(
    auto_error=False,
    scheme_name="collectorToken",
    description=(
        "Source-scoped bearer credential; only a SHA-256 hash is configured on the receiver"
    ),
)


class ObservationInput(Observation, Input):
    pass


@router.post(
    "/admin/observations/{source_id}",
    status_code=204,
    summary="Publish a private telemetry observation",
    description=(
        "Private collector endpoint, protected by a source-scoped bearer "
        "token independent of browser administrator sessions. Maximum 16 KiB, "
        "two-second body timeout. Kind/runtime must match the configured "
        "source; samples older than five minutes, over five seconds into the "
        "future, or out of order are refused. Never publish content or "
        "secrets."
    ),
    responses=error_responses(
        {
            400: "MALFORMED_REQUEST: invalid JSON",
            401: "Invalid source credential",
            409: "STALE_OBSERVATION: sample is not newer",
            413: "Observation too large or too slow",
            422: "Invalid observation or source scope",
        }
    ),
)
async def publish(
    source_id: Annotated[
        str,
        Path(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$", description="Opaque configured source alias"),
    ],
    payload: ObservationInput,
    store: Observations,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(collector_token)],
) -> Response:
    if credentials is None or not store.authorized(source_id, credentials.credentials):
        raise ApiError(401, ErrorCode.UNAUTHENTICATED, "Invalid collector credential")
    store.accept(source_id, payload, datetime.now(UTC))
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
