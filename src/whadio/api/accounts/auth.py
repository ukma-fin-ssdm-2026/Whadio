from datetime import timedelta
from typing import Annotated, Final

from fastapi import Depends, Response
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer

from ..core.errors import ApiError, ErrorCode
from .fixtures import ALICE, DEMO_EXTENSION_TOKEN, DEMO_SESSION_TOKEN
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


async def _browser_user(cookie: Cookie) -> UserRead:
    if cookie != DEMO_SESSION_TOKEN:
        raise _unauthenticated()
    return ALICE


async def _capture_user(cookie: Cookie, bearer: Bearer) -> UserRead:
    if bearer is not None:
        if bearer.credentials != DEMO_EXTENSION_TOKEN:
            raise _unauthenticated()
        return ALICE
    return await _browser_user(cookie)


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
