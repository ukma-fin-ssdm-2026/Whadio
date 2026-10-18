import asyncio
from contextlib import AbstractAsyncContextManager
from uuid import UUID, uuid4

from pydantic import HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from ..accounts.contracts import UserProfile
from ..notifications.services import NotificationDrainer, Recipient
from ..notifications.settings import NotificationSettings, SmtpSettings
from .composition import AccountRecipients, notification_drainer


class UnusedDatabase:
    def transaction(self) -> AbstractAsyncContextManager[AsyncSession]:
        raise AssertionError("composing the drainer opens no transaction")


class Profiles:
    def __init__(self, profiles: dict[UUID, UserProfile]) -> None:
        self._profiles: dict[UUID, UserProfile] = profiles

    async def profile(self, user_id: UUID) -> UserProfile | None:
        return self._profiles.get(user_id)


def settings(smtp: SmtpSettings | None) -> NotificationSettings:
    return NotificationSettings(smtp=smtp, public_url=HttpUrl("https://whadio.example.com"))


def test_scheduler_without_a_relay_has_no_drainer() -> None:
    # Act
    drainer = notification_drainer(settings(None), UnusedDatabase())
    # Assert
    assert drainer is None


def test_scheduler_with_a_relay_drains_the_outbox() -> None:
    # Arrange
    relay = SmtpSettings(host="127.0.0.1", port=1025, starttls=False, from_address="w@localhost")
    # Act
    drainer = notification_drainer(settings(relay), UnusedDatabase())
    # Assert
    assert isinstance(drainer, NotificationDrainer)


def test_recipient_is_the_name_and_email_of_the_account() -> None:
    # Arrange
    user_id = uuid4()
    recipients = AccountRecipients(
        Profiles({user_id: UserProfile("Olena Koval", "olena@example.com")})
    )
    # Act
    found = asyncio.run(recipients.recipient(user_id))
    # Assert
    assert found == Recipient("Olena Koval", "olena@example.com")


def test_recipient_without_an_account_is_missing() -> None:
    # Arrange
    recipients = AccountRecipients(Profiles({}))
    # Act
    found = asyncio.run(recipients.recipient(uuid4()))
    # Assert
    assert found is None
