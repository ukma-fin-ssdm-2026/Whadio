from uuid import uuid4

import pytest
from httpx import Response
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ..core.errors import ErrorResponse
from .schemas import SessionRead

pytestmark = pytest.mark.slow

PASSWORD = uuid4().hex


def test_browser_sign_in_sets_an_http_only_session_cookie(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.post(
                "/api/v1/sessions", json={"email": user.email, "password": PASSWORD}
            )
            return response.status_code, "".join(response.headers.get_list("set-cookie"))

    status, cookie = async_database.run(scenario)
    # Assert
    assert (status, cookie.startswith("whadio_session="), "HttpOnly" in cookie) == (
        201,
        True,
        True,
    )


def test_session_cookie_signs_the_browser_in(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        async with AsyncDatabase.api_client(session) as client:
            await client.post("/api/v1/sessions", json={"email": user.email, "password": PASSWORD})
            # Act
            response = await client.get("/api/v1/workspaces")
            return response.status_code

    status = async_database.run(scenario)
    # Assert
    assert status == 200


def test_wrong_password_is_refused(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.post(
                "/api/v1/sessions", json={"email": user.email, "password": uuid4().hex}
            )
            return response.status_code, error_code(response)

    found = async_database.run(scenario)
    # Assert
    assert found == (401, "INVALID_CREDENTIALS")


def test_extension_sign_in_returns_a_token_and_no_cookie(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[bool, bool]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.post(
                "/api/v1/sessions",
                json={"email": user.email, "password": PASSWORD, "kind": "extension"},
            )
            token = SessionRead.model_validate_json(response.content).token
            return bool(token), "set-cookie" in response.headers

    found = async_database.run(scenario)
    # Assert
    assert found == (True, False)


def test_extension_token_does_not_open_the_web_app(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        async with AsyncDatabase.api_client(session) as client:
            signed = await client.post(
                "/api/v1/sessions",
                json={"email": user.email, "password": PASSWORD, "kind": "extension"},
            )
            token = SessionRead.model_validate_json(signed.content).token
            # Act
            response = await client.get(
                "/api/v1/workspaces", headers={"Authorization": f"Bearer {token}"}
            )
            return response.status_code

    status = async_database.run(scenario)
    # Assert
    assert status == 401


def test_signed_out_cookie_no_longer_works(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        async with AsyncDatabase.api_client(session) as client:
            signed = await client.post(
                "/api/v1/sessions", json={"email": user.email, "password": PASSWORD}
            )
            cookie = signed.cookies["whadio_session"]
            await client.delete("/api/v1/sessions/current")
            # Act
            response = await client.get(
                "/api/v1/workspaces", headers={"Cookie": f"whadio_session={cookie}"}
            )
            return response.status_code

    status = async_database.run(scenario)
    # Assert
    assert status == 401


def test_sign_out_without_a_session_succeeds(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.delete("/api/v1/sessions/current")
            return response.status_code

    status = async_database.run(scenario)
    # Assert
    assert status == 204


def test_sign_in_with_an_invalid_address_is_a_validation_error(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.post(
                "/api/v1/sessions", json={"email": "not an address", "password": PASSWORD}
            )
            return response.status_code, error_code(response)

    found = async_database.run(scenario)
    # Assert
    assert found == (422, "VALIDATION_ERROR")


def error_code(response: Response) -> str:
    return ErrorResponse.model_validate_json(response.content).error.code
