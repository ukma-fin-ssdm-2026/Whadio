from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase, SavepointTransactions

from ...accounts.enums import RegistrationMode
from ...accounts.password_resets import AddressMailHistory
from ...accounts.registration_requests import IRegistrationMailQueue, RegistrationMail
from ...accounts.repositories import RegistrationRepository, SessionRepository
from ...accounts.services import RegistrationIssuer
from ...notifications.models import NotificationOutbox
from ...notifications.templates import NoticeKind
from ..app import create_app
from ..composition import RuntimeIntegrations, outbox_password_reset_mail, runtime_database
from ..core.errors import ErrorCode, ErrorResponse
from ..settings import WebSettings
from .schemas import UserRead
from .test_routes_password_reset_requests import public_response

pytestmark = pytest.mark.slow

REGISTRATION_PATH = "/api/v1/registrations"
ACCEPTED = (
    202,
    (
        b'{"message":"We\'ll email that address a link to continue, unless we sent one in the '
        b'last 20 minutes."}'
    ),
    "no-store",
)


def settings(mode: RegistrationMode) -> WebSettings:
    return WebSettings.model_validate({"registration_mode": mode, "broker": None})


def test_new_known_and_repeated_addresses_get_the_same_response(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[tuple[int, bytes, str]]:
        user = await AsyncDatabase.add_account(session, f"A1{uuid4().hex}")
        new = f"{uuid4()}@example.com"
        async with AsyncDatabase.api_client(
            session, web_settings=settings(RegistrationMode.VERIFIED)
        ) as client:
            # Act
            responses = [
                await client.post(REGISTRATION_PATH, json={"email": email})
                for email in (new, user.email, new)
            ]
        return [public_response(response) for response in responses]

    # Assert
    assert async_database.run(scenario) == [ACCEPTED] * 3


def test_new_address_is_queued_as_a_link_without_a_recipient_account(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[tuple[UUID | None, NoticeKind]]:
        email = f"{uuid4()}@example.com"
        async with AsyncDatabase.api_client(
            session, web_settings=settings(RegistrationMode.VERIFIED)
        ) as client:
            # Act
            await client.post(REGISTRATION_PATH, json={"email": email})
        pending = await RegistrationRepository(session).pending_for(email)
        if pending is None:
            raise AssertionError("no registration was issued")
        rows = await session.execute(
            select(NotificationOutbox.recipient_user_id, NotificationOutbox.kind).where(
                NotificationOutbox.dedupe_key.startswith(
                    f"{NoticeKind.REGISTRATION_LINK}:{pending.pending_registration_id}:"
                )
            )
        )
        return [(recipient, kind) for recipient, kind in rows]

    # Assert
    assert async_database.run(scenario) == [(None, NoticeKind.REGISTRATION_LINK)]


def test_invite_only_instance_refuses_registration_requests(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, ErrorCode]:
        async with AsyncDatabase.api_client(
            session, web_settings=settings(RegistrationMode.INVITE_ONLY)
        ) as client:
            # Act
            response = await client.post(REGISTRATION_PATH, json={"email": "a@example.com"})
        return response.status_code, ErrorResponse.model_validate_json(response.content).error.code

    # Assert
    assert async_database.run(scenario) == (403, ErrorCode.INVITE_ONLY_INSTANCE)


def test_registration_request_refuses_an_invalid_address(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, list[str | None]]:
        async with AsyncDatabase.api_client(
            session, web_settings=settings(RegistrationMode.VERIFIED)
        ) as client:
            # Act
            response = await client.post(REGISTRATION_PATH, json={"email": "not an address"})
        details = ErrorResponse.model_validate_json(response.content).error.details
        return response.status_code, [detail.field for detail in details]

    # Assert
    assert async_database.run(scenario) == (422, ["email"])


class FailingRegistrationMail:
    """Fails after the pending registration exists, naming the address as a driver might."""

    def __init__(self, email: str) -> None:
        self._email: str = email

    async def history(self, email: str, now: datetime, /) -> AddressMailHistory:
        del email, now
        return AddressMailHistory(waiting=False, last_sent_at=None)

    async def reserve(self, mail: RegistrationMail, /) -> None:
        raise RuntimeError(f"cannot queue registration {mail.registration_id} for {self._email}")


def test_failed_queueing_answers_the_same_rolls_back_and_logs_no_address(
    async_database: AsyncDatabase, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange
    email = f"{uuid4()}@example.com"

    def failing_registration_mail(session: AsyncSession) -> IRegistrationMailQueue:
        del session
        return FailingRegistrationMail(email)

    async def scenario(session: AsyncSession) -> tuple[tuple[int, bytes, str], bool]:
        app = create_app(
            web_settings=settings(RegistrationMode.VERIFIED),
            integrations=RuntimeIntegrations(
                password_reset_mail=outbox_password_reset_mail,
                registration_mail=failing_registration_mail,
            ),
        )
        app.dependency_overrides[runtime_database] = lambda: SavepointTransactions(session)
        async with AsyncClient(
            transport=ASGITransport(app), base_url="https://example.com"
        ) as client:
            # Act
            response = await client.post(REGISTRATION_PATH, json={"email": email})
        rolled_back = await RegistrationRepository(session).pending_for(email) is None
        return public_response(response), rolled_back

    # Assert
    assert (async_database.run(scenario), email in caplog.text) == ((ACCEPTED, True), False)


def test_reset_request_soon_after_an_emailed_registration_sends_nothing(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[NoticeKind]:
        email = f"{uuid4()}@example.com"
        async with AsyncDatabase.api_client(
            session, web_settings=settings(RegistrationMode.VERIFIED)
        ) as client:
            await client.post(REGISTRATION_PATH, json={"email": email})
            pending = await RegistrationRepository(session).pending_for(email)
            if pending is None:
                raise AssertionError("no registration was issued")
            await session.execute(
                update(NotificationOutbox)
                .where(
                    NotificationOutbox.dedupe_key.startswith(
                        f"{NoticeKind.REGISTRATION_LINK}:{pending.pending_registration_id}:"
                    )
                )
                .values(sent_at=datetime.now(UTC))
            )
            renewed = await RegistrationIssuer(
                RegistrationRepository(session), SessionRepository(session)
            ).renew(pending.pending_registration_id, pending.created_at, datetime.now(UTC))
            if renewed is None:
                raise AssertionError("the emailed link is not current")
            created = await client.post(
                f"{REGISTRATION_PATH}/{pending.pending_registration_id}/complete",
                json={
                    "token": renewed.link.token,
                    "name": "Alice",
                    "password": f"A1{uuid4().hex}",
                    "accept_terms": True,
                },
            )
            # Act
            await client.post("/api/v1/password-resets", json={"email": email})
        kinds = await session.scalars(
            select(NotificationOutbox.kind).where(
                NotificationOutbox.recipient_user_id
                == UserRead.model_validate_json(created.content).id
            )
        )
        return list(kinds)

    # Assert
    assert async_database.run(scenario) == []


def test_registration_request_refuses_a_non_ascii_name_before_the_at(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, list[str | None]]:
        async with AsyncDatabase.api_client(
            session, web_settings=settings(RegistrationMode.VERIFIED)
        ) as client:
            # Act
            response = await client.post(REGISTRATION_PATH, json={"email": "josé@example.com"})
        details = ErrorResponse.model_validate_json(response.content).error.details
        return response.status_code, [detail.field for detail in details]

    # Assert
    assert async_database.run(scenario) == (422, ["email"])
