from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from ...shared.errors import Failure, UseCaseError
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

    @app.get("/failures/{failure}")
    async def fail(failure: Failure) -> None:
        raise UseCaseError(failure)

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


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (
            Failure.INTEGRATION_UNAVAILABLE,
            "A service Whadio depends on is unavailable; try again later",
        ),
        (Failure.NOT_FOUND, "Not found, or you have no access to it"),
        (Failure.INSUFFICIENT_ROLE, "Your role in this workspace does not allow this"),
        (Failure.VALIDATION_ERROR, "Request contains invalid fields"),
        (Failure.TRANSCRIPT_EXISTS, "This meeting already has a transcript"),
        (
            Failure.FOLDER_RECOVERY_CONFLICT,
            "The folder cannot be restored over an existing one",
        ),
        (Failure.DEFAULT_FOLDER, "The default folder cannot be changed this way"),
        (Failure.ALREADY_PROCESSED, "This was already processed"),
        (Failure.INVALID_CREDENTIALS, "Unknown email address or wrong password"),
        (Failure.PERSONAL_WORKSPACE, "A personal workspace cannot be changed this way"),
        (Failure.FOLDER_EXISTS, "A folder with this name already exists"),
        (Failure.TERM_EXISTS, "This glossary term already exists"),
        (Failure.NOT_TRANSCRIBED, "The meeting has not been transcribed yet"),
        (Failure.STALE_REVISION, "The transcript changed since you loaded it"),
        (Failure.LINK_INVALID, "The link is invalid or has expired"),
        (Failure.ACCESS_REQUEST_EXISTS, "You have already requested access"),
        (Failure.ALREADY_HAS_ACCESS, "You already have access"),
        (Failure.ACCESS_REQUEST_NOT_PENDING, "The access request was already answered"),
        (Failure.SHARE_ALREADY_BOUND, "The share is already bound to another account"),
        (Failure.SHARE_REVOKED, "The share was revoked"),
        (Failure.NOTES_IN_PROGRESS, "Notes are already being written"),
        (Failure.REGENERATION_LIMIT, "The notes cannot be regenerated again yet"),
        (Failure.RECORDING_NOT_READY, "The recording is not ready yet"),
        (Failure.RECORDING_DELETED, "The recording was deleted"),
        (
            Failure.CHUNK_MISMATCH,
            "Different audio is already stored under this chunk number",
        ),
        (Failure.CAPTURE_CLOSED, "The capture was already completed"),
        (Failure.MISSING_CHUNKS, "Some chunks never arrived"),
        (Failure.EMPTY_CAPTURE, "No chunk of the recording arrived"),
    ],
)
def test_use_case_failure_has_a_readable_message(failure: Failure, message: str) -> None:
    # Arrange
    client = _client()

    # Act
    response = client.get(f"/failures/{failure.value}")

    # Assert
    assert ErrorResponse.model_validate_json(response.text).error.message == message
