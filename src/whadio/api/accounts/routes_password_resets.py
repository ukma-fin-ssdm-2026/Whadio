from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Response

from ...accounts.password_resets import PasswordResetMailKind, PasswordResetValidationError
from ..composition import PasswordResetRequests, PasswordResets
from ..core.errors import (
    DOC_INVALID,
    DOC_MALFORMED,
    ApiError,
    ErrorCode,
    ErrorDetail,
    error_responses,
)
from .auth import clear_session_cookie
from .schemas import PasswordResetAccepted, PasswordResetComplete, PasswordResetRequest

router = APIRouter(tags=["accounts"])


@router.post(
    "/password-resets",
    status_code=202,
    summary="Request a password-reset link",
    description="Public in verified mode. Returns a fixed confirmation for every valid email "
    "address. A known address can receive a single-use link valid for one hour, with a "
    "20-minute window between email requests.",
    response_description="Request accepted",
    openapi_extra={"security": []},
    responses=error_responses(
        {
            400: DOC_MALFORMED,
            403: "INVITE_ONLY_INSTANCE: the operator runs the instance invite-only",
            422: DOC_INVALID,
            503: "INTEGRATION_UNAVAILABLE: reset delivery or the database is unconfigured",
        }
    ),
)
async def request_password_reset(
    payload: PasswordResetRequest, response: Response, service: PasswordResetRequests
) -> PasswordResetAccepted:
    await service.request(payload.email, datetime.now(UTC), kind=PasswordResetMailKind.RESET)
    response.headers["Cache-Control"] = "no-store"
    return PasswordResetAccepted(
        message="If an account exists for that email, we'll send a reset link."
    )


@router.post(
    "/password-resets/{reset_id}/complete",
    status_code=204,
    summary="Set a new password from a reset link",
    description="Public in either registration mode. Consumes the single-use link, changes the "
    "password and ends every browser and extension session atomically. MCP keys remain active.",
    response_description="Password changed; sign in again with the new password",
    openapi_extra={"security": []},
    responses=error_responses(
        {
            400: DOC_MALFORMED,
            404: "LINK_INVALID: unknown, expired, replaced or used link",
            422: DOC_INVALID,
        }
    ),
)
async def complete(
    reset_id: Annotated[UUID, Path(description="Password-reset identifier from the link")],
    payload: PasswordResetComplete,
    response: Response,
    service: PasswordResets,
) -> None:
    try:
        await service.complete(
            reset_id,
            payload.token.get_secret_value(),
            payload.password.get_secret_value(),
            datetime.now(UTC),
        )
    except PasswordResetValidationError as error:
        raise ApiError(
            422,
            ErrorCode.VALIDATION_ERROR,
            "Request contains invalid fields",
            [ErrorDetail(field="password", message=str(error))],
        ) from None
    clear_session_cookie(response)
    response.headers["Cache-Control"] = "no-store"
