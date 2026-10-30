import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...accounts.models import PendingRegistration, User, Workspace, WorkspaceMembership
from ...accounts.passwords import Argon2PasswordHasher
from ...accounts.repositories import RegistrationRepository, SessionRepository
from ...accounts.services import AccountAlreadyExistsError, RegistrationIssuer, RegistrationLink
from ...meetings.models import Folder
from ..core.errors import ErrorResponse
from .schemas import UserRead

pytestmark = pytest.mark.slow
PASSWORD = f"  A1{uuid4().hex}  "


async def issue(session: AsyncSession, now: datetime | None = None) -> RegistrationLink:
    return await RegistrationIssuer(
        RegistrationRepository(session), SessionRepository(session)
    ).issue(f"{uuid4()}@example.com", now or datetime.now(UTC))


def test_operator_link_stores_only_a_hash(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        # Act
        link = await issue(session)
        pending = await session.get(PendingRegistration, link.registration_id)
        return (
            pending is not None
            and pending.token_hash == hashlib.sha256(link.token.encode()).hexdigest()
        )

    # Assert
    assert async_database.run(scenario)


def test_reissue_replaces_the_token_case_insensitively(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[bool, bool]:
        issuer = RegistrationIssuer(RegistrationRepository(session), SessionRepository(session))
        email = f"{uuid4()}@example.com"
        now = datetime.now(UTC)
        first = await issuer.issue(email, now)
        # Act
        second = await issuer.issue(email.upper(), now + timedelta(minutes=1))
        return first.registration_id == second.registration_id, first.token != second.token

    # Assert
    assert async_database.run(scenario) == (True, True)


def test_issuer_refuses_an_existing_account(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> None:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        issuer = RegistrationIssuer(RegistrationRepository(session), SessionRepository(session))
        # Act
        with pytest.raises(AccountAlreadyExistsError):
            await issuer.issue(user.email.upper(), datetime.now(UTC))

    # Assert
    async_database.run(scenario)


def test_registration_creates_a_personal_workspace_and_signs_in(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, bool, bool, bool, int]:
        link = await issue(session)
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.post(
                f"/api/v1/registrations/{link.registration_id}/complete",
                json={
                    "token": link.token,
                    "name": "Alice",
                    "password": PASSWORD,
                    "accept_terms": True,
                },
            )
            user = UserRead.model_validate_json(response.content)
            workspace = await session.scalar(
                select(Workspace)
                .join(WorkspaceMembership)
                .where(
                    WorkspaceMembership.user_id == user.id,
                    WorkspaceMembership.role == "Owner",
                    Workspace.is_personal.is_(True),
                )
            )
            folder = (
                None
                if workspace is None
                else await session.scalar(
                    select(Folder).where(
                        Folder.workspace_id == workspace.workspace_id,
                        Folder.is_default.is_(True),
                    )
                )
            )
            stored = await session.get(User, user.id)
            password_ok = stored is not None and Argon2PasswordHasher().verify(
                stored.password_hash, PASSWORD
            )
            authenticated = await client.get("/api/v1/workspaces")
            return (
                response.status_code,
                folder is not None,
                password_ok,
                stored is not None and stored.terms_accepted_at <= datetime.now(UTC),
                authenticated.status_code,
            )

    # Assert
    assert async_database.run(scenario) == (201, True, True, True, 200)


@pytest.mark.parametrize(
    "reason", ["unknown", "wrong", "expired", "replaced", "used", "registered"]
)
def test_unusable_links_have_one_error(async_database: AsyncDatabase, reason: str) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str]:
        now = datetime.now(UTC)
        link = await issue(session, now - timedelta(days=2) if reason == "expired" else now)
        token, registration_id = link.token, link.registration_id
        if reason == "unknown":
            registration_id = uuid4()
        elif reason == "wrong":
            token = uuid4().hex
        elif reason == "replaced":
            pending = await session.get(PendingRegistration, registration_id)
            assert pending is not None
            await RegistrationIssuer(
                RegistrationRepository(session), SessionRepository(session)
            ).issue(pending.email, now)
        elif reason == "registered":
            pending = await session.get(PendingRegistration, registration_id)
            assert pending is not None
            await AsyncDatabase.add_account(session, PASSWORD, email=pending.email.upper())
        async with AsyncDatabase.api_client(session) as client:
            payload = {"token": token, "name": "Alice", "password": PASSWORD, "accept_terms": True}
            if reason == "used":
                await client.post(f"/api/v1/registrations/{registration_id}/complete", json=payload)
            # Act
            response = await client.post(
                f"/api/v1/registrations/{registration_id}/complete", json=payload
            )
            return response.status_code, ErrorResponse.model_validate_json(
                response.content
            ).error.code.value

    # Assert
    assert async_database.run(scenario) == (404, "LINK_INVALID")


@pytest.mark.parametrize("password", ["shortA1", "lowercase123456", "UppercaseOnly", "A1" * 65])
def test_weak_password_is_a_field_error_and_does_not_consume_link(
    async_database: AsyncDatabase,
    password: str,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str | None, bool]:
        link = await issue(session)
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.post(
                f"/api/v1/registrations/{link.registration_id}/complete",
                json={
                    "token": link.token,
                    "name": "Alice",
                    "password": password,
                    "accept_terms": True,
                },
            )
            error = ErrorResponse.model_validate_json(response.content).error
            return (
                response.status_code,
                error.details[0].field,
                await session.get(PendingRegistration, link.registration_id) is not None,
            )

    # Assert
    assert async_database.run(scenario) == (422, "password", True)


@pytest.mark.parametrize("terms", [False, "true", 1, None])
def test_terms_require_explicit_true(
    async_database: AsyncDatabase, *, terms: bool | str | int | None
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, bool]:
        link = await issue(session)
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.post(
                f"/api/v1/registrations/{link.registration_id}/complete",
                json={
                    "token": link.token,
                    "name": "Alice",
                    "password": PASSWORD,
                    "accept_terms": terms,
                },
            )
            return response.status_code, await session.get(
                PendingRegistration, link.registration_id
            ) is not None

    # Assert
    assert async_database.run(scenario) == (422, True)


def test_registration_cookie_has_security_attributes(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        link = await issue(session)
        async with AsyncDatabase.api_client(session) as client:
            # Act
            response = await client.post(
                f"/api/v1/registrations/{link.registration_id}/complete",
                json={
                    "token": link.token,
                    "name": "Alice",
                    "password": PASSWORD,
                    "accept_terms": True,
                },
            )
            cookie = response.headers["set-cookie"]
            return all(value in cookie for value in ("HttpOnly", "Secure", "SameSite=strict"))

    # Assert
    assert async_database.run(scenario)
