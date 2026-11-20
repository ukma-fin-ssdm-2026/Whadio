from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...accounts.enums import RegistrationMode
from ...accounts.password_resets import PasswordResetMailKind
from ...accounts.test_password_reset_requests import ResetMailQueue
from ..app import create_app
from ..composition import RuntimeIntegrations, transaction
from ..core.errors import ErrorCode, ErrorResponse
from ..settings import WebSettings

RESET_PATH = "/api/v1/password-resets"
VERIFIED = WebSettings.model_validate(
    {"registration_mode": RegistrationMode.VERIFIED, "broker": None}
)


@asynccontextmanager
async def client_with_reset_mail(
    session: AsyncSession, mail: ResetMailQueue
) -> AsyncGenerator[AsyncClient]:
    app = create_app(
        web_settings=VERIFIED, integrations=RuntimeIntegrations(password_reset_mail=lambda _: mail)
    )

    async def savepoint() -> AsyncGenerator[AsyncSession]:
        async with session.begin_nested():
            yield session

    app.dependency_overrides[transaction] = savepoint
    async with AsyncClient(transport=ASGITransport(app), base_url="https://example.com") as client:
        yield client


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
            return [
                (response.status_code, response.content, response.headers["Cache-Control"])
                for response in responses
            ]

    # Assert
    responses = async_database.run(scenario)
    assert (responses, [notice.kind for notice in mail.messages]) == (
        [
            (
                202,
                b'{"message":"If an account exists for that email, we\'ll send a reset link."}',
                "no-store",
            )
        ]
        * 3,
        [PasswordResetMailKind.RESET],
    )


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

    app.dependency_overrides[transaction] = unexpected_database
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
