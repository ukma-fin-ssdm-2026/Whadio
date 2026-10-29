from typing import Annotated

from fastapi import APIRouter, Depends

from ...accounts.enums import RegistrationMode
from ..composition import api_version, registration_mode
from .schemas import InstanceRead

router = APIRouter(tags=["accounts"])


@router.get(
    "/instance",
    summary="Describe this instance",
    description="Public. Returns the registration mode and API version so the web app can "
    "decide whether to offer registration and password reset.",
    openapi_extra={"security": []},
)
async def instance(
    version: Annotated[str, Depends(api_version)],
    mode: Annotated[RegistrationMode, Depends(registration_mode)],
) -> InstanceRead:
    return InstanceRead(
        registration_mode=mode,
        api_version=version,
    )
