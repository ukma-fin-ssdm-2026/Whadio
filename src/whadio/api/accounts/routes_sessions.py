from datetime import UTC, datetime

from fastapi import APIRouter, Response

from ...accounts import enums
from ..composition import SignIns
from ..core.errors import DOC_INVALID, DOC_MALFORMED, ErrorCode, error_responses
from .auth import Bearer, Cookie, clear_session_cookie, set_session_cookie, user_read
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
async def sign_in(payload: SignIn, response: Response, sign_ins: SignIns) -> SessionRead:
    signed = await sign_ins.sign_in(
        payload.email, payload.password, enums.SessionKind(payload.kind.value), datetime.now(UTC)
    )
    if payload.kind is SessionKind.EXTENSION:
        return SessionRead(
            kind=payload.kind,
            expires_at=signed.expires_at,
            user=user_read(signed.user),
            token=signed.token,
        )
    set_session_cookie(response, signed.token, signed.expires_at)
    return SessionRead(kind=payload.kind, expires_at=signed.expires_at, user=user_read(signed.user))


@router.delete(
    "/sessions/current",
    status_code=204,
    summary="Sign out",
    description=(
        "Ends the sessions presented by the cookie and by the extension's bearer token, and "
        "clears the cookie. Always `204`, also without a session: signing out is idempotent."
    ),
    response_description="Signed out",
)
async def sign_out(response: Response, cookie: Cookie, bearer: Bearer, sign_ins: SignIns) -> None:
    await sign_ins.sign_out(
        [
            token
            for token in (cookie, None if bearer is None else bearer.credentials)
            if token is not None
        ]
    )
    clear_session_cookie(response)
