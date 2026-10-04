from fastapi import APIRouter
from pydantic import Field

from .core.schemas import Output

router = APIRouter(tags=["meta"])


class Health(Output):
    status: str = Field(
        description="Always `ok` while the process serves requests", examples=["ok"]
    )


@router.get(
    "/health",
    summary="Liveness probe",
    description="Unauthenticated liveness check for uptime monitoring. Not versioned.",
    response_description="The service is up",
)
async def health() -> Health:
    return Health(status="ok")
