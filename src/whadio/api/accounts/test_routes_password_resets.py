from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...accounts.enums import SessionKind
from ...accounts.models import PasswordReset
from ...accounts.passwords import Argon2PasswordHasher
from ...accounts.repositories import IdentityRepository, SessionRepository
from ...accounts.services import SignInService
from ..composition import mcp_key_service, password_reset_service
from ..core.errors import ErrorResponse

pytestmark = pytest.mark.slow
PASSWORD = f"  New1{uuid4().hex}  "


@pytest.mark.parametrize("reason", ["unknown", "wrong", "expired", "replaced", "used"])
def test_unusable_links_have_one_error(async_database: AsyncDatabase, reason: str) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        service = password_reset_service(session)
        now = datetime.now(UTC)
        link = await service.issue(
            user.email, now - timedelta(hours=2) if reason == "expired" else now
        )
        reset_id = uuid4() if reason == "unknown" else link.reset_id
        token = uuid4().hex if reason == "wrong" else link.token
        if reason == "replaced":
            await service.issue(user.email.upper(), now + timedelta(seconds=1))
        if reason == "used":
            await service.complete(reset_id, token, PASSWORD, now)
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.post(
                f"/api/v1/password-resets/{reset_id}/complete",
                json={"token": token, "password": PASSWORD},
            )
            error = ErrorResponse.model_validate_json(response.content).error
            return response.status_code, error.code.value

    # Assert
    assert async_database.run(scenario) == (404, "LINK_INVALID")


@pytest.mark.parametrize("password", ["shortA1", "lowercase123456", "UppercaseOnly", "A1" * 65])
def test_password_error_names_field_without_echoing_secrets(
    async_database: AsyncDatabase, password: str
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str | None, bool, bool]:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        link = await password_reset_service(session).issue(user.email, datetime.now(UTC))
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.post(
                f"/api/v1/password-resets/{link.reset_id}/complete",
                json={"token": link.token, "password": password},
            )
            error = ErrorResponse.model_validate_json(response.content).error
            return (
                response.status_code,
                error.details[0].field,
                password not in response.text and link.token not in response.text,
                await session.get(PasswordReset, link.reset_id) is not None,
            )

    # Assert
    assert async_database.run(scenario) == (422, "password", True, True)


@pytest.mark.parametrize("mode", ["invite-only", "verified"])
def test_reset_changes_password_and_clears_cookie_in_either_mode(
    async_database: AsyncDatabase, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_REGISTRATION_MODE", mode)

    async def scenario(session: AsyncSession) -> tuple[int, bytes, bool, int, int]:
        old_password = f"Old1{uuid4().hex}"
        user = await AsyncDatabase.add_account(session, old_password)
        link = await password_reset_service(session).issue(user.email, datetime.now(UTC))
        async with AsyncDatabase.api_client(session) as client:
            await client.post(
                "/api/v1/sessions", json={"email": user.email, "password": old_password}
            )
            # Act
            response = await client.post(
                f"/api/v1/password-resets/{link.reset_id}/complete",
                json={"token": link.token, "password": PASSWORD},
            )
            old = await client.post(
                "/api/v1/sessions", json={"email": user.email, "password": old_password}
            )
            new = await client.post(
                "/api/v1/sessions", json={"email": user.email, "password": PASSWORD}
            )
            return (
                response.status_code,
                response.content,
                "Max-Age=0" in response.headers["set-cookie"],
                old.status_code,
                new.status_code,
            )

    # Assert
    assert async_database.run(scenario) == (204, b"", True, 401, 201)


def test_reset_revokes_every_session_but_preserves_mcp_and_other_accounts(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        other = await AsyncDatabase.add_account(session, PASSWORD)
        now = datetime.now(UTC)
        sign_ins = SignInService(SessionRepository(session), Argon2PasswordHasher())
        browser = await sign_ins.sign_in(user.email, PASSWORD, SessionKind.BROWSER, now)
        extension = await sign_ins.sign_in(user.email, PASSWORD, SessionKind.EXTENSION, now)
        second = await sign_ins.sign_in(user.email, PASSWORD, SessionKind.BROWSER, now)
        unrelated = await sign_ins.sign_in(other.email, PASSWORD, SessionKind.BROWSER, now)
        key = await mcp_key_service(session).create(user.user_id, None, now)
        link = await password_reset_service(session).issue(user.email, now)
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.post(
                f"/api/v1/password-resets/{link.reset_id}/complete",
                json={"token": link.token, "password": PASSWORD},
            )
        identities = IdentityRepository(session)
        return (
            response.status_code == 204
            and await identities.session_user(browser.token, SessionKind.BROWSER, now) is None
            and await identities.session_user(second.token, SessionKind.BROWSER, now) is None
            and await identities.session_user(extension.token, SessionKind.EXTENSION, now) is None
            and await identities.session_user(unrelated.token, SessionKind.BROWSER, now) is not None
            and await identities.mcp_user(key.secret, now) is not None
        )

    # Assert
    assert async_database.run(scenario)
