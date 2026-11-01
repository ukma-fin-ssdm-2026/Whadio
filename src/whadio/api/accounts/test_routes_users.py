from datetime import timedelta
from uuid import uuid4

import pytest
from httpx import Response
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...accounts.enums import SessionKind
from ...accounts.models import User
from ..core.errors import ErrorResponse
from .schemas import SessionRead, UserRead

pytestmark = pytest.mark.slow

PASSWORD = uuid4().hex


async def _add_account(session: AsyncSession, *, is_administrator: bool = False) -> User:
    user = await AsyncDatabase.add_account(session, PASSWORD, name="Olena Admin")
    user.is_administrator = is_administrator
    await session.flush()
    await session.refresh(user)
    return user


def _error(response: Response) -> tuple[int, str]:
    return response.status_code, ErrorResponse.model_validate_json(response.content).error.code


def test_signed_in_user_is_returned_for_the_session_cookie(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, UserRead, UserRead]:
        user = await _add_account(session)
        token = await AsyncDatabase.add_session(session, user, SessionKind.BROWSER)
        async with AsyncDatabase.api_client(session) as client:
            client.cookies.set("whadio_session", token)
            # Act
            response = await client.get("/api/v1/users/me")
            found = UserRead.model_validate_json(response.content)
            expected = UserRead(
                id=user.user_id,
                email=user.email,
                name=user.name,
                is_administrator=False,
                created_at=user.created_at,
            )
            return response.status_code, found, expected

    status, found, expected = async_database.run(scenario)
    # Assert
    assert (status, found) == (200, expected)


def test_administrator_is_reported_as_an_administrator(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await _add_account(session, is_administrator=True)
        token = await AsyncDatabase.add_session(session, user, SessionKind.BROWSER)
        async with AsyncDatabase.api_client(session) as client:
            client.cookies.set("whadio_session", token)
            # Act
            response = await client.get("/api/v1/users/me")
            return UserRead.model_validate_json(response.content).is_administrator

    found = async_database.run(scenario)
    # Assert
    assert found is True


def test_revoked_administrator_is_no_longer_one_on_the_next_request(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[bool, bool]:
        user = await _add_account(session, is_administrator=True)
        token = await AsyncDatabase.add_session(session, user, SessionKind.BROWSER)
        async with AsyncDatabase.api_client(session) as client:
            client.cookies.set("whadio_session", token)
            before = await client.get("/api/v1/users/me")
            user.is_administrator = False
            await session.flush()
            # Act
            after = await client.get("/api/v1/users/me")
            return (
                UserRead.model_validate_json(before.content).is_administrator,
                UserRead.model_validate_json(after.content).is_administrator,
            )

    found = async_database.run(scenario)
    # Assert
    assert found == (True, False)


def test_signed_in_user_without_a_session_is_unauthenticated(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.get("/api/v1/users/me")
            return _error(response)

    found = async_database.run(scenario)
    # Assert
    assert found == (401, "UNAUTHENTICATED")


def test_signed_in_user_with_an_expired_session_is_unauthenticated(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        user = await _add_account(session)
        token = await AsyncDatabase.add_session(
            session, user, SessionKind.BROWSER, expires_in=-timedelta(days=1)
        )
        async with AsyncDatabase.api_client(session) as client:
            client.cookies.set("whadio_session", token)
            # Act
            response = await client.get("/api/v1/users/me")
            return _error(response)

    found = async_database.run(scenario)
    # Assert
    assert found == (401, "UNAUTHENTICATED")


def test_signed_in_user_after_sign_out_is_unauthenticated(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        user = await _add_account(session)
        async with AsyncDatabase.api_client(session) as client:
            signed = await client.post(
                "/api/v1/sessions", json={"email": user.email, "password": PASSWORD}
            )
            cookie = signed.cookies["whadio_session"]
            await client.delete("/api/v1/sessions/current")
            client.cookies.set("whadio_session", cookie)
            # Act
            response = await client.get("/api/v1/users/me")
            return _error(response)

    found = async_database.run(scenario)
    # Assert
    assert found == (401, "UNAUTHENTICATED")


def test_extension_token_as_a_bearer_is_unauthenticated(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        user = await _add_account(session)
        async with AsyncDatabase.api_client(session) as client:
            signed = await client.post(
                "/api/v1/sessions",
                json={"email": user.email, "password": PASSWORD, "kind": "extension"},
            )
            token = SessionRead.model_validate_json(signed.content).token
            # Act
            response = await client.get(
                "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
            )
            return _error(response)

    found = async_database.run(scenario)
    # Assert
    assert found == (401, "UNAUTHENTICATED")


def test_extension_token_in_the_session_cookie_is_unauthenticated(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        user = await _add_account(session)
        token = await AsyncDatabase.add_session(session, user, SessionKind.EXTENSION)
        async with AsyncDatabase.api_client(session) as client:
            client.cookies.set("whadio_session", token)
            # Act
            response = await client.get("/api/v1/users/me")
            return _error(response)

    found = async_database.run(scenario)
    # Assert
    assert found == (401, "UNAUTHENTICATED")


def test_browser_session_token_as_a_bearer_is_unauthenticated(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        user = await _add_account(session)
        token = await AsyncDatabase.add_session(session, user, SessionKind.BROWSER)
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.get(
                "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
            )
            return _error(response)

    found = async_database.run(scenario)
    # Assert
    assert found == (401, "UNAUTHENTICATED")
