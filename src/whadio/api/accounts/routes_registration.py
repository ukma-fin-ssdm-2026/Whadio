from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Response

from ...accounts.services import RegistrationDetails, RegistrationValidationError
from ..composition import RegistrationRequests, Registrations
from ..core.errors import (
    DOC_INVALID,
    DOC_MALFORMED,
    ApiError,
    ErrorCode,
    ErrorDetail,
    error_responses,
)
from .auth import set_session_cookie, user_read
from .schemas import RegistrationAccepted, RegistrationComplete, RegistrationRequest, UserRead

router = APIRouter(tags=["accounts"])


@router.post(
    "/registrations",
    status_code=202,
    summary="Request a registration link",
    description="Public in verified mode. Returns a fixed confirmation for every valid email "
    "address. A new address can receive a single-use link valid for 24 hours, and an address "
    "with an account a sign-in reminder with a password-reset link instead. A repeat within 20 "
    "minutes of the last email changes nothing.",
    response_description="Request accepted",
    openapi_extra={"security": []},
    responses=error_responses(
        {
            400: DOC_MALFORMED,
            403: "INVITE_ONLY_INSTANCE: the operator runs the instance invite-only",
            422: DOC_INVALID,
            503: "INTEGRATION_UNAVAILABLE: email delivery or the database is unconfigured",
        }
    ),
)
async def request_registration(
    payload: RegistrationRequest, response: Response, service: RegistrationRequests
) -> RegistrationAccepted:
    await service.request(payload.email)
    response.headers["Cache-Control"] = "no-store"
    return RegistrationAccepted(
        message="We'll email that address a link to continue, unless we sent one in the last "
        "20 minutes."
    )


@router.post(
    "/registrations/{registration_id}/complete",
    status_code=201,
    summary="Create the account from a registration link",
    description="Works in either registration mode. Creates the account and its personal workspace "
    "atomically, consumes the link, and sets the browser session cookie.",
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
    registration_id: Annotated[UUID, Path(description="Registration identifier from the link")],
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
