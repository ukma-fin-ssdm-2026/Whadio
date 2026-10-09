import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final

from fastapi import Depends, Response
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from ..core.db import Db
from ..core.errors import ApiError, ErrorCode
from .models import User, UserSession
from .schemas import SessionKind, UserRead

SESSION_COOKIE: Final = "whadio_session"
BROWSER_SESSION_TTL: Final = timedelta(days=14)
EXTENSION_TOKEN_TTL: Final = timedelta(hours=24)

session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    auto_error=False,
    scheme_name="sessionCookie",
    description="HttpOnly cookie set by `POST /api/v1/sessions`; the browser sends it "
    "automatically",
)
extension_token = HTTPBearer(
    auto_error=False,
    scheme_name="extensionToken",
    description="Token from `POST /api/v1/sessions` with `kind: extension`; accepted only "
    "by the capture endpoints and by sign-out",
)

Cookie = Annotated[str | None, Depends(session_cookie)]
Bearer = Annotated[HTTPAuthorizationCredentials | None, Depends(extension_token)]


async def _user_for_token(db: Db, token: str | None, kind: SessionKind) -> UserRead:
    user = None
    if token is not None:
        user = await db.scalar(
            select(User)
            .join(UserSession, UserSession.user_id == User.user_id)
            .where(
                UserSession.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                UserSession.kind == kind,
                UserSession.expires_at > datetime.now(UTC),
            )
        )
    if user is None:
        raise ApiError(
            401,
            ErrorCode.UNAUTHENTICATED,
            "Sign in first: the session is missing, expired or ended",
        )
    return user.to_read()


async def _browser_user(db: Db, cookie: Cookie) -> UserRead:
    return await _user_for_token(db, cookie, SessionKind.BROWSER)


async def _capture_user(db: Db, cookie: Cookie, bearer: Bearer) -> UserRead:
    if bearer is not None:
        return await _user_for_token(db, bearer.credentials, SessionKind.EXTENSION)
    return await _user_for_token(db, cookie, SessionKind.BROWSER)


BrowserUser = Annotated[UserRead, Depends(_browser_user)]
CaptureUser = Annotated[UserRead, Depends(_capture_user)]


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=True, samesite="strict", path="/")
