import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Response
from sqlalchemy import delete, select

from ..core.db import Db
from ..core.errors import DOC_INVALID, DOC_MALFORMED, ApiError, ErrorCode, error_responses
from .auth import (
    BROWSER_SESSION_TTL,
    EXTENSION_TOKEN_TTL,
    Bearer,
    Cookie,
    clear_session_cookie,
    set_session_cookie,
)
from .models import User, UserSession
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
async def sign_in(payload: SignIn, response: Response, db: Db) -> SessionRead:
    user = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not hmac.compare_digest(
        user.password_hash,
        # The lowercased email is the salt, so equal passwords still hash differently per user.
        hashlib.sha256((payload.email.lower() + payload.password).encode()).hexdigest(),
    ):
        raise ApiError(401, ErrorCode.INVALID_CREDENTIALS, "Wrong email address or password")

    now = datetime.now(UTC)
    ttl = EXTENSION_TOKEN_TTL if payload.kind is SessionKind.EXTENSION else BROWSER_SESSION_TTL
    token = secrets.token_urlsafe(32)
    session = UserSession(
        user_id=user.user_id,
        kind=payload.kind,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        created_at=now,
        expires_at=now + ttl,
    )
    db.add(session)
    await db.commit()

    if payload.kind is SessionKind.EXTENSION:
        return SessionRead(
            kind=payload.kind, expires_at=session.expires_at, user=user.to_read(), token=token
        )
    set_session_cookie(response, token)
    return SessionRead(kind=payload.kind, expires_at=session.expires_at, user=user.to_read())


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
async def sign_out(response: Response, db: Db, cookie: Cookie, bearer: Bearer) -> None:
    token = bearer.credentials if bearer is not None else cookie
    if token is not None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        await db.execute(delete(UserSession).where(UserSession.token_hash == token_hash))
        await db.commit()
    clear_session_cookie(response)
