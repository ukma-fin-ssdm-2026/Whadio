from datetime import UTC, datetime, timedelta
from typing import Annotated, Final

from fastapi import Depends, Response
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer

from ...accounts.enums import SessionKind
from ...accounts.repositories import IdentityRepository
from ...accounts.services import IdentityService
from ..composition import Session
from ..core.errors import ApiError, ErrorCode
from .fixtures import DEMO_SESSION_TOKEN
from .schemas import UserRead

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


def _unauthenticated() -> ApiError:
    return ApiError(
        401, ErrorCode.UNAUTHENTICATED, "Sign in first: the session is missing, expired or ended"
    )


def _browser_credentials(cookie: Cookie) -> str:
    if cookie is None:
        raise _unauthenticated()
    return cookie


BrowserCredentials = Annotated[str, Depends(_browser_credentials)]


async def _browser_user(token: BrowserCredentials, session: Session) -> UserRead:
    user = await IdentityService(IdentityRepository(session)).session_user(
        token, SessionKind.BROWSER, datetime.now(UTC)
    )
    if user is None:
        raise _unauthenticated()
    return UserRead(
        id=user.user_id,
        email=user.email,
        name=user.name,
        is_administrator=user.is_administrator,
        created_at=user.created_at,
    )


async def _capture_user(cookie: Cookie, bearer: Bearer, session: Session) -> UserRead:
    if bearer is not None:
        user = await IdentityService(IdentityRepository(session)).session_user(
            bearer.credentials, SessionKind.EXTENSION, datetime.now(UTC)
        )
        if user is None:
            raise _unauthenticated()
        return UserRead(
            id=user.user_id,
            email=user.email,
            name=user.name,
            is_administrator=user.is_administrator,
            created_at=user.created_at,
        )
    return await _browser_user(_browser_credentials(cookie), session)


BrowserUser = Annotated[UserRead, Depends(_browser_user)]
CaptureUser = Annotated[UserRead, Depends(_capture_user)]


def set_session_cookie(response: Response) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        DEMO_SESSION_TOKEN,
        max_age=int(BROWSER_SESSION_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=True, samesite="strict", path="/")
