from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from pydantic import HttpUrl
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase, Mailpit, SavepointTransactions

from .accounts.enums import RegistrationMode
from .api.settings import WebSettings
from .notifications.models import NotificationOutbox
from .notifications.settings import NotificationSettings, SmtpSettings
from .scheduler.composition import notification_drainer

PUBLIC_URL = "https://whadio.example.com"


@pytest.mark.slow
def test_emailed_registration_link_creates_the_account(async_database: AsyncDatabase) -> None:
    # Arrange
    mailpit, email = Mailpit(), f"{uuid4()}@example.com"
    relay = SmtpSettings(
        host="127.0.0.1",
        port=mailpit.mailpit_smtp_port,
        starttls=False,
        from_address="whadio@localhost",
    )
    verified = WebSettings.model_validate(
        {"registration_mode": RegistrationMode.VERIFIED, "broker": None}
    )

    async def scenario(session: AsyncSession) -> int:
        # The test database may hold unsent notices; the rollback restores them.
        await session.execute(
            update(NotificationOutbox)
            .where(NotificationOutbox.sent_at.is_(None))
            .values(sent_at=datetime.now(UTC))
        )
        drainer = notification_drainer(
            NotificationSettings(smtp=relay, public_url=HttpUrl(PUBLIC_URL)),
            SavepointTransactions(session),
        )
        if drainer is None:
            raise AssertionError("the relay is configured, so the scheduler drains")
        async with AsyncDatabase.api_client(session, web_settings=verified) as client:
            # Act
            await client.post("/api/v1/registrations", json={"email": email})
            await drainer.drain()
            message = mailpit.wait_for(lambda mail: [to.address for to in mail.to] == [email])
            if message is None:
                raise AssertionError("the registration email did not reach Mailpit")
            link = urlsplit(
                next(word for word in mailpit.text(message).split() if word.startswith(PUBLIC_URL))
            )
            response = await client.post(
                f"/api/v1{link.path}/complete",
                json={
                    "token": link.fragment.removeprefix("token="),
                    "name": "Alice",
                    "password": f"A1{uuid4().hex}",
                    "accept_terms": True,
                },
            )
        return response.status_code

    # Assert
    assert async_database.run(scenario) == 201
