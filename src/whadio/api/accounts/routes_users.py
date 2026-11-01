from fastapi import APIRouter

from ..core.errors import DOC_UNAUTHENTICATED, error_responses
from .auth import BrowserUser
from .schemas import UserRead

router = APIRouter(tags=["accounts"])


@router.get(
    "/users/me",
    summary="Get the signed-in user",
    description="Returns the user behind the browser session cookie. The extension's bearer "
    "token is not accepted.",
    response_description="The signed-in user",
    responses=error_responses({401: DOC_UNAUTHENTICATED}),
)
async def get_signed_in_user(user: BrowserUser) -> UserRead:
    return user
