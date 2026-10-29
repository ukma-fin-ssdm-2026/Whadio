from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Response

from ...accounts.services import RegistrationDetails, RegistrationValidationError
from ..composition import Registrations
from ..core.errors import (
    DOC_INVALID,
    DOC_MALFORMED,
    ApiError,
    ErrorCode,
    ErrorDetail,
    error_responses,
)
from .auth import set_session_cookie, user_read
from .schemas import RegistrationComplete, UserRead

router = APIRouter(tags=["accounts"])


@router.post(
    "/registrations/{registration_id}/complete",
    status_code=201,
    summary="Create the account from a registration link",
    description="Works in either registration mode. Creates the account and its personal workspace "
    "atomically, consumes the link, and sets the browser session cookie.",
    responses=error_responses(
        {
            400: DOC_MALFORMED,
            404: "LINK_INVALID: unknown, expired, replaced or used link",
            422: DOC_INVALID,
        }
    ),
)
async def complete(
    registration_id: UUID,
    payload: RegistrationComplete,
    response: Response,
    service: Registrations,
) -> UserRead:
    try:
        signed = await service.complete(
            registration_id,
            payload.token.get_secret_value(),
            RegistrationDetails(
                payload.name, payload.password.get_secret_value(), payload.accept_terms
            ),
            now=datetime.now(UTC),
        )
    except RegistrationValidationError as error:
        raise ApiError(
            422,
            ErrorCode.VALIDATION_ERROR,
            "Request contains invalid fields",
            [ErrorDetail(field=error.field_name, message=str(error))],
        ) from None
    set_session_cookie(response, signed.token, signed.expires_at)
    response.headers["Cache-Control"] = "no-store"
    return user_read(signed.user)
