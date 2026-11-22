from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from .models import User
from .password_resets import PasswordResetMailKind, PasswordResetRequestService
from .registration_requests import RegistrationMail, RegistrationRequestService
from .repositories import RegistrationRepository, SessionRepository
from .reset_repository import PasswordResetRepository
from .services import RegistrationIssuer
from .test_password_reset_requests import MailQueue, ResetMailQueue
from .test_password_resets import PASSWORD

pytestmark = pytest.mark.slow


class RegistrationMailQueue(MailQueue[RegistrationMail]):
    pass


@dataclass
class Mailbox:
    registrations: RegistrationMailQueue = field(default_factory=RegistrationMailQueue)
    resets: ResetMailQueue = field(default_factory=ResetMailQueue)


async def request(session: AsyncSession, email: str, now: datetime, mailbox: Mailbox) -> None:
    sessions = SessionRepository(session)
    resets = PasswordResetRequestService(
        PasswordResetRepository(session), sessions, mailbox.resets, lambda: now
    )
    await RegistrationRequestService(
        RegistrationRepository(session), sessions, resets, mailbox.registrations, lambda: now
    ).request(email)


async def stored_token_hash(session: AsyncSession, email: str) -> str | None:
    pending = await RegistrationRepository(session).pending_for(email)
    return None if pending is None else pending.token_hash


def test_new_address_gets_a_24_hour_registration_link(async_database: AsyncDatabase) -> None:
    # Arrange
    mailbox = Mailbox()

    async def scenario(session: AsyncSession) -> bool:
        email, now = f"{uuid4()}@example.com", datetime.now(UTC)
        # Act
        await request(session, email, now, mailbox)
        pending = await RegistrationRepository(session).pending_for(email)
        return pending is not None and mailbox.registrations.messages == [
            RegistrationMail(pending.pending_registration_id, email, now, now + timedelta(hours=24))
        ]

    # Assert
    assert async_database.run(scenario)


def test_registration_request_creates_no_account(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        email = f"{uuid4()}@example.com"
        # Act
        await request(session, email, datetime.now(UTC), Mailbox())
        return await session.scalar(select(User.user_id).where(User.email == email)) is None

    # Assert
    assert async_database.run(scenario)


def test_address_with_an_account_gets_a_sign_in_reminder_instead(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    mailbox = Mailbox()

    async def scenario(session: AsyncSession) -> None:
        user = await AsyncDatabase.add_account(session, PASSWORD)
        # Act
        await request(session, user.email.upper(), datetime.now(UTC), mailbox)

    async_database.run(scenario)
    # Assert
    assert (
        [mail.kind for mail in mailbox.resets.messages],
        mailbox.registrations.messages,
    ) == ([PasswordResetMailKind.SIGN_IN_REMINDER], [])


def test_repeat_within_20_minutes_of_delivery_queues_nothing_and_keeps_the_link(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    mailbox = Mailbox()

    async def scenario(session: AsyncSession) -> tuple[int, bool]:
        email, now = f"{uuid4()}@example.com", datetime.now(UTC)
        await request(session, email, now, mailbox)
        mailbox.registrations.deliver(now)
        earlier = await stored_token_hash(session, email)
        # Act
        await request(session, email, now + timedelta(minutes=20, microseconds=-1), mailbox)
        return len(mailbox.registrations.messages), await stored_token_hash(
            session, email
        ) == earlier

    # Assert
    assert async_database.run(scenario) == (1, True)


def test_repeat_20_minutes_after_delivery_queues_a_link_that_replaces_the_earlier_one(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    mailbox = Mailbox()

    async def scenario(session: AsyncSession) -> tuple[int, bool]:
        email, now = f"{uuid4()}@example.com", datetime.now(UTC)
        await request(session, email, now, mailbox)
        mailbox.registrations.deliver(now)
        earlier = await stored_token_hash(session, email)
        # Act
        await request(session, email, now + timedelta(minutes=20), mailbox)
        return len(mailbox.registrations.messages), await stored_token_hash(
            session, email
        ) != earlier

    # Assert
    assert async_database.run(scenario) == (2, True)


def test_operator_link_does_not_use_up_the_email_window(async_database: AsyncDatabase) -> None:
    # Arrange
    mailbox = Mailbox()

    async def scenario(session: AsyncSession) -> None:
        email, now = f"{uuid4()}@example.com", datetime.now(UTC)
        await RegistrationIssuer(RegistrationRepository(session), SessionRepository(session)).issue(
            email, now
        )
        # Act
        await request(session, email, now + timedelta(minutes=1), mailbox)

    async_database.run(scenario)
    # Assert
    assert len(mailbox.registrations.messages) == 1


def test_repeat_while_the_registration_email_waits_queues_nothing(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    mailbox = Mailbox()

    async def scenario(session: AsyncSession) -> None:
        email, now = f"{uuid4()}@example.com", datetime.now(UTC)
        await request(session, email, now, mailbox)
        # Act
        await request(session, email, now + timedelta(hours=1), mailbox)

    async_database.run(scenario)
    # Assert
    assert len(mailbox.registrations.messages) == 1
