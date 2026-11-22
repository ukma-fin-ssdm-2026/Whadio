from asyncio import CancelledError
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import override
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...accounts.enums import RegistrationMode
from ...accounts.models import PasswordReset, User
from ...accounts.password_resets import PasswordResetMail, PasswordResetMailKind
from ...accounts.test_password_reset_requests import ResetMailQueue
from ...notifications.models import NotificationOutbox
from ...notifications.repositories import NotificationOutboxRepository
from ...notifications.templates import ProcessingFinished
from ..app import create_app
from ..composition import RuntimeIntegrations, password_reset_service, runtime_database
from ..core.errors import ErrorCode, ErrorResponse
from ..settings import WebSettings

RESET_PATH = "/api/v1/password-resets"
ACCEPTED_RESPONSE = (
    202,
    b'{"message":"If an account exists for that email, we\'ll send a reset link."}',
    "no-store",
)
VERIFIED = WebSettings.model_validate(
    {"registration_mode": RegistrationMode.VERIFIED, "broker": None}
)


class ResetRequestTransactions:
    def __init__(self, session: AsyncSession, mail: ResetMailQueue, *, fail_on_exit: bool) -> None:
        self._session: AsyncSession = session
        self._mail: ResetMailQueue = mail
        self._fail_on_exit: bool = fail_on_exit

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        async with self._session.begin_nested():
            reservations_before = len(self._mail.messages)
            yield self._session
            if self._fail_on_exit and len(self._mail.messages) > reservations_before:
                await self._session.execute(text("SELECT 1 / 0"))


class FailingResetMailQueue(ResetMailQueue):
    @override
    async def reserve(self, mail: PasswordResetMail, /) -> None:
        await super().reserve(mail)
        raise RuntimeError(f"Synthetic reservation failure with token {mail.link.token}")


class CancelledResetMailQueue(ResetMailQueue):
    @override
    async def reserve(self, mail: PasswordResetMail, /) -> None:
        raise CancelledError


class StoredResetMailQueue:
    """Persist a marker through the outbox and capture the reset request in memory."""

    def __init__(self, session: AsyncSession, recorder: ResetMailQueue) -> None:
        self._outbox: NotificationOutboxRepository = NotificationOutboxRepository(session)
        self._recorder: ResetMailQueue = recorder

    async def reserve(self, mail: PasswordResetMail, /) -> None:
        await self._outbox.reserve(
            mail.user_id,
            f"reset-test:{mail.link.reset_id}",
            ProcessingFinished(meeting_id=mail.link.reset_id, meeting_name="Reset test"),
        )
        await self._recorder.reserve(mail)


@asynccontextmanager
async def client_with_reset_mail(
    session: AsyncSession, mail: ResetMailQueue, *, fail_on_exit: bool = False
) -> AsyncGenerator[AsyncClient]:
    def mail_factory(transaction_session: AsyncSession) -> StoredResetMailQueue:
        assert transaction_session is session
        return StoredResetMailQueue(transaction_session, mail)

    app = create_app(
        web_settings=VERIFIED, integrations=RuntimeIntegrations(password_reset_mail=mail_factory)
    )

    transactions = ResetRequestTransactions(session, mail, fail_on_exit=fail_on_exit)
    app.dependency_overrides[runtime_database] = lambda: transactions
    async with AsyncClient(transport=ASGITransport(app), base_url="https://example.com") as client:
        yield client


def public_response(response: Response) -> tuple[int, bytes, str]:
    return response.status_code, response.content, response.headers["Cache-Control"]


async def mail_reservation_count(session: AsyncSession, user_id: UUID) -> int:
    rows = await session.scalars(
        select(NotificationOutbox.notice_id).where(NotificationOutbox.recipient_user_id == user_id)
    )
    return len(rows.all())


@pytest.mark.slow
def test_known_unknown_and_recently_queued_addresses_get_the_same_response(
    async_database: AsyncDatabase, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange
    mail = ResetMailQueue()

    async def scenario(session: AsyncSession) -> tuple[list[tuple[int, bytes, str]], int]:
        user = await AsyncDatabase.add_account(session, "OriginalPassword1")
        async with client_with_reset_mail(session, mail) as client:
            # Act
            responses = [
                await client.post(RESET_PATH, json={"email": email})
                for email in (user.email, f"{uuid4()}@example.com", user.email.upper())
            ]
        return [public_response(response) for response in responses], await mail_reservation_count(
            session, user.user_id
        )

    # Assert
    responses, reservation_count = async_database.run(scenario)
    logged_failures = [
        record for record in caplog.records if record.name == "whadio.api.composition"
    ]
    assert (
        responses,
        reservation_count,
        [notice.kind for notice in mail.messages],
        logged_failures,
    ) == (
        [ACCEPTED_RESPONSE] * 3,
        1,
        [PasswordResetMailKind.RESET],
        [],
    )


@pytest.mark.slow
@pytest.mark.parametrize("fail_on_exit", [False, True], ids=["reserve", "transaction-exit"])
def test_reset_request_failure_preserves_the_link_and_fixed_response(
    async_database: AsyncDatabase, caplog: pytest.LogCaptureFixture, *, fail_on_exit: bool
) -> None:
    # Arrange
    mail = ResetMailQueue() if fail_on_exit else FailingResetMailQueue()

    async def scenario(session: AsyncSession) -> tuple[bool, ...]:
        user = await AsyncDatabase.add_account(session, "OriginalPassword1")
        user_id, email = user.user_id, user.email
        previous = await password_reset_service(session).issue(email, datetime.now(UTC))
        previous_hash = (await session.get_one(PasswordReset, previous.reset_id)).token_hash
        async with client_with_reset_mail(session, mail, fail_on_exit=fail_on_exit) as client:
            # Act
            known = await client.post(RESET_PATH, json={"email": email})
            unknown = await client.post(RESET_PATH, json={"email": f"{uuid4()}@example.com"})
        pending = await session.get_one(PasswordReset, previous.reset_id, populate_existing=True)
        account = await session.get_one(User, user_id, populate_existing=True)
        (attempted_mail,) = mail.messages
        logs = [
            record.getMessage()
            for record in caplog.records
            if record.name == "whadio.api.composition"
        ]
        return (
            public_response(known) == public_response(unknown) == ACCEPTED_RESPONSE,
            pending.token_hash == previous_hash,
            account.password_reset_mail_queued_at is None,
            await mail_reservation_count(session, user_id) == 0,
            logs == ["Could not queue a password reset email"],
            email not in caplog.text and attempted_mail.link.token not in caplog.text,
        )

    # Assert
    assert async_database.run(scenario) == (True, True, True, True, True, True)


@pytest.mark.slow
def test_cancelled_reset_request_rolls_back_the_mail_reservation(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        user = await AsyncDatabase.add_account(session, "OriginalPassword1")
        user_id, email = user.user_id, user.email
        async with client_with_reset_mail(session, CancelledResetMailQueue()) as client:
            # Act
            with pytest.raises(CancelledError):
                await client.post(RESET_PATH, json={"email": email})
        return await mail_reservation_count(session, user_id)

    # Assert
    assert async_database.run(scenario) == 0


@pytest.mark.parametrize(
    ("mode", "queue_configured", "status_code", "code"),
    [
        (RegistrationMode.INVITE_ONLY, False, 403, ErrorCode.INVITE_ONLY_INSTANCE),
        (RegistrationMode.INVITE_ONLY, True, 403, ErrorCode.INVITE_ONLY_INSTANCE),
        (RegistrationMode.VERIFIED, False, 503, ErrorCode.INTEGRATION_UNAVAILABLE),
    ],
)
def test_mode_and_queue_availability_checked_before_the_database(
    mode: RegistrationMode, status_code: int, code: ErrorCode, *, queue_configured: bool
) -> None:
    # Arrange
    def mail_factory(_session: AsyncSession) -> ResetMailQueue:
        pytest.fail("A refused request should not need a mail queue")

    app = create_app(
        web_settings=WebSettings.model_validate({"registration_mode": mode, "broker": None}),
        integrations=RuntimeIntegrations(
            password_reset_mail=mail_factory if queue_configured else None
        ),
    )

    def unexpected_database() -> None:
        pytest.fail("The request should have been refused before opening a transaction")

    app.dependency_overrides[runtime_database] = unexpected_database
    # Act
    response = TestClient(app).post(RESET_PATH, json={"email": "alice@example.com"})
    # Assert
    assert (
        response.status_code,
        ErrorResponse.model_validate_json(response.content).error.code,
    ) == (status_code, code)


@pytest.mark.slow
def test_invalid_email_is_rejected_without_echoing_the_value(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, str | None, bool]:
        email = "private-text-without-an-address"
        async with client_with_reset_mail(session, ResetMailQueue()) as client:
            # Act
            response = await client.post(RESET_PATH, json={"email": email})
            detail = ErrorResponse.model_validate_json(response.content).error.details[0]
            return response.status_code, detail.field, email in response.text

    # Assert
    assert async_database.run(scenario) == (422, "email", False)
