from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from ..accounts.schemas import SignIn
from .errors import ErrorResponse, register_error_handlers


def _client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/sessions")
    async def sign_in(_payload: SignIn) -> None:
        return None

    @app.get("/meetings/{meeting_id}")
    async def get_meeting(meeting_id: UUID, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> str:
        return f"{meeting_id}:{limit}"

    return TestClient(app)


def test_invalid_password_is_left_out_of_the_validation_error() -> None:
    # Arrange
    client = _client()
    password = uuid4().hex * 5

    # Act
    response = client.post("/sessions", json={"email": "alice@whadio.dev", "password": password})

    # Assert
    assert password not in response.text


def test_invalid_body_field_is_named_without_its_value() -> None:
    # Arrange
    client = _client()
    password = uuid4().hex * 5

    # Act
    response = client.post("/sessions", json={"email": "alice@whadio.dev", "password": password})

    # Assert
    detail = ErrorResponse.model_validate_json(response.text).error.details[0]
    assert (detail.field, detail.provided_value) == ("password", None)


def test_invalid_query_parameter_is_echoed() -> None:
    # Arrange
    client = _client()

    # Act
    response = client.get(f"/meetings/{uuid4()}", params={"limit": 500})

    # Assert
    detail = ErrorResponse.model_validate_json(response.text).error.details[0]
    assert (detail.field, detail.provided_value) == ("limit", "500")


def test_invalid_path_parameter_is_echoed() -> None:
    # Arrange
    client = _client()

    # Act
    response = client.get("/meetings/not-a-uuid")

    # Assert
    detail = ErrorResponse.model_validate_json(response.text).error.details[0]
    assert (detail.field, detail.provided_value) == ("meeting_id", "not-a-uuid")
