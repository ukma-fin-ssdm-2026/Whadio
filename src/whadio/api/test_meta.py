from fastapi.testclient import TestClient

from .main import app
from .meta import Health


def test_health_reports_ok() -> None:
    # Arrange
    client = TestClient(app)

    # Act
    response = client.get("/health")

    # Assert
    assert (response.status_code, Health.model_validate_json(response.text)) == (
        200,
        Health(status="ok"),
    )
