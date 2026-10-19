from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from ...accounts.administrators import AdministratorRepository
from ...accounts.models import User
from ...accounts.repositories import IdentityRepository
from ...processing.monitoring import JobMonitoring
from ..app import create_app
from ..composition import transaction
from ..core.errors import ErrorCode, ErrorResponse


@pytest.mark.parametrize("endpoint", ["jobs", "metrics"])
@pytest.mark.parametrize(
    "phase", ["transaction_start", "authentication", "permission", "query", "transaction_end"]
)
def test_monitoring_database_outages_return_safe_service_unavailable(
    monkeypatch: pytest.MonkeyPatch, endpoint: str, phase: str
) -> None:
    # Arrange
    error = OperationalError("select", {}, Exception("private database failure"))
    user = User(
        user_id=uuid4(),
        email="admin@example.com",
        name="Admin",
        is_administrator=True,
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(IdentityRepository, "session_user", AsyncMock(return_value=user))
    monkeypatch.setattr(AdministratorRepository, "enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(JobMonitoring, "jobs", AsyncMock(return_value=[]))
    monkeypatch.setattr(JobMonitoring, "counts", AsyncMock(return_value=[]))
    if phase == "authentication":
        monkeypatch.setattr(IdentityRepository, "session_user", AsyncMock(side_effect=error))
    elif phase == "permission":
        monkeypatch.setattr(AdministratorRepository, "enabled", AsyncMock(side_effect=error))
    elif phase == "query":
        monkeypatch.setattr(
            JobMonitoring, "jobs" if endpoint == "jobs" else "counts", AsyncMock(side_effect=error)
        )

    async def database_transaction() -> AsyncGenerator[AsyncSession]:
        if phase == "transaction_start":
            raise error
        async with AsyncSession() as session:
            yield session
        if phase == "transaction_end":
            raise error

    app = create_app()
    app.dependency_overrides[transaction] = database_transaction
    client = TestClient(app)
    client.cookies.set("whadio_session", "test-session")
    # Act
    response = client.get(f"/api/v1/admin/{endpoint}")
    body = ErrorResponse.model_validate_json(response.content)
    # Assert
    assert (response.status_code, body.error.code, "private" in response.text) == (
        503,
        ErrorCode.INTEGRATION_UNAVAILABLE,
        False,
    )
