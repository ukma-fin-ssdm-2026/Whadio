from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import override
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...accounts.enums import RegistrationMode
from ...accounts.models import PasswordReset, User
from ...accounts.password_resets import PasswordResetMail, PasswordResetMailKind
from ...accounts.test_password_reset_requests import ResetMailQueue
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
    def __init__(self, session: AsyncSession, *, fail_at_commit: bool) -> None:
        self._session: AsyncSession = session
        self._fail_at_commit: bool = fail_at_commit

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        async with self._session.begin_nested():
            yield self._session
            if self._fail_at_commit:
                raise RuntimeError("Synthetic commit failure")


class FailingResetMailQueue(ResetMailQueue):
    @override
    async def reserve(self, mail: PasswordResetMail, /) -> None:
        await super().reserve(mail)
        raise RuntimeError(f"Synthetic reservation failure with token {mail.link.token}")


@asynccontextmanager
async def client_with_reset_mail(
    session: AsyncSession, mail: ResetMailQueue, *, fail_at_commit: bool = False
) -> AsyncGenerator[AsyncClient]:
    def mail_factory(transaction_session: AsyncSession) -> ResetMailQueue:
        assert transaction_session is session
        return mail

    app = create_app(
        web_settings=VERIFIED, integrations=RuntimeIntegrations(password_reset_mail=mail_factory)
    )

    transactions = ResetRequestTransactions(session, fail_at_commit=fail_at_commit)
    app.dependency_overrides[runtime_database] = lambda: transactions
    async with AsyncClient(transport=ASGITransport(app), base_url="https://example.com") as client:
        yield client


def public_response(response: Response) -> tuple[int, bytes, str]:
    return response.status_code, response.content, response.headers["Cache-Control"]


@pytest.mark.slow
def test_known_unknown_and_recently_queued_addresses_get_the_same_response(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    mail = ResetMailQueue()

    async def scenario(session: AsyncSession) -> list[tuple[int, bytes, str]]:
        user = await AsyncDatabase.add_account(session, "OriginalPassword1")
        async with client_with_reset_mail(session, mail) as client:
            # Act
            responses = [
                await client.post(RESET_PATH, json={"email": email})
                for email in (user.email, f"{uuid4()}@example.com", user.email.upper())
            ]
            return [public_response(response) for response in responses]

    # Assert
    responses = async_database.run(scenario)
    assert (responses, [notice.kind for notice in mail.messages]) == (
        [ACCEPTED_RESPONSE] * 3,
        [PasswordResetMailKind.RESET],
    )


@pytest.mark.slow
@pytest.mark.parametrize("fail_at_commit", [False, True], ids=["reserve", "commit"])
def test_reset_request_failure_preserves_the_link_and_fixed_response(
    async_database: AsyncDatabase, caplog: pytest.LogCaptureFixture, *, fail_at_commit: bool
) -> None:
    # Arrange
    mail = ResetMailQueue() if fail_at_commit else FailingResetMailQueue()

    async def scenario(session: AsyncSession) -> tuple[bool, ...]:
        user = await AsyncDatabase.add_account(session, "OriginalPassword1")
        user_id, email = user.user_id, user.email
        previous = await password_reset_service(session).issue(email, datetime.now(UTC))
        previous_hash = (await session.get_one(PasswordReset, previous.reset_id)).token_hash
        async with client_with_reset_mail(session, mail, fail_at_commit=fail_at_commit) as client:
            # Act
            known = await client.post(RESET_PATH, json={"email": email})
            unknown = await client.post(RESET_PATH, json={"email": f"{uuid4()}@example.com"})
        pending = await session.get_one(PasswordReset, previous.reset_id, populate_existing=True)
        account = await session.get_one(User, user_id, populate_existing=True)
        (attempted_mail,) = mail.messages
        logs = [record for record in caplog.records if record.name == "whadio.api.composition"]
        return (
            public_response(known) == public_response(unknown) == ACCEPTED_RESPONSE,
            pending.token_hash == previous_hash,
            account.password_reset_mail_queued_at is None,
            any(record.getMessage() == "Could not queue a password reset email" for record in logs),
            email not in caplog.text and attempted_mail.link.token not in caplog.text,
        )

    # Assert
    assert async_database.run(scenario) == (True, True, True, True, True)


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
