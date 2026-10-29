from typing import Annotated

from fastapi import APIRouter, Depends

from ..composition import api_version
from ..settings import WebSettings
from .schemas import InstanceRead

router = APIRouter(tags=["accounts"])


@router.get(
    "/instance",
    summary="Describe this instance",
    description="Public. Returns the registration mode and API version so the web app can "
    "decide whether to offer registration and password reset.",
    openapi_extra={"security": []},
)
async def instance(version: Annotated[str, Depends(api_version)]) -> InstanceRead:
    return InstanceRead(
        registration_mode=WebSettings.model_validate({}).registration_mode,
        api_version=version,
    )
