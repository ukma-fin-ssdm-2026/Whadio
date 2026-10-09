from datetime import UTC, datetime

from fastapi import APIRouter, Response

from ..core.errors import DOC_INVALID, DOC_MALFORMED, ApiError, ErrorCode, error_responses
from .auth import (
    BROWSER_SESSION_TTL,
    EXTENSION_TOKEN_TTL,
    clear_session_cookie,
    set_session_cookie,
)
from .fixtures import ALICE, DEMO_EMAIL, DEMO_EXTENSION_TOKEN, DEMO_PASSWORD
from .schemas import SessionKind, SessionRead, SignIn

router = APIRouter(tags=["accounts"])


@router.post(
    "/sessions",
    status_code=201,
    summary="Sign in",
    description=(
        "Public. With `kind: browser` (the default) sets an HttpOnly, SameSite=Strict "
        "session cookie valid for 14 days. With `kind: extension` returns a bearer token, "
        "shown once and valid for 24 hours, that only the capture endpoints accept. Neither "
        "is extended by use. A failure never says which credential was wrong."
    ),
    response_description="The session that was started",
    responses=error_responses(
        {
            400: DOC_MALFORMED,
            401: f"`{ErrorCode.INVALID_CREDENTIALS}`: unknown address or wrong password",
            422: DOC_INVALID,
            429: f"`{ErrorCode.RATE_LIMITED}`: too many sign-in attempts from this address; "
            "`Retry-After` says how long to wait",
        }
    ),
)
async def sign_in(payload: SignIn, response: Response) -> SessionRead:
    if (payload.email, payload.password) != (DEMO_EMAIL, DEMO_PASSWORD):
        raise ApiError(401, ErrorCode.INVALID_CREDENTIALS, "Wrong email address or password")
    now = datetime.now(UTC)
    if payload.kind is SessionKind.EXTENSION:
        return SessionRead(
            kind=payload.kind,
            expires_at=now + EXTENSION_TOKEN_TTL,
            user=ALICE,
            token=DEMO_EXTENSION_TOKEN,
        )
    set_session_cookie(response)
    return SessionRead(kind=payload.kind, expires_at=now + BROWSER_SESSION_TTL, user=ALICE)


@router.delete(
    "/sessions/current",
    status_code=204,
    summary="Sign out",
    description=(
        "Ends the session presented by the cookie or the extension's bearer token and clears "
        "the cookie. Always `204`, also without a session: signing out is idempotent."
    ),
    response_description="Signed out",
)
async def sign_out(response: Response) -> None:
    clear_session_cookie(response)
