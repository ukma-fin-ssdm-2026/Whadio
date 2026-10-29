import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from typer.testing import CliRunner

from conftest import AsyncDatabase

from .accounts.models import PasswordReset, User
from .accounts.password_resets import PasswordResetService
from .accounts.passwords import Argon2PasswordHasher
from .accounts.reset_repository import PasswordResetRepository
from .cli import app
from .shared.database import Database, DatabaseSettings


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHADIO_PUBLIC_URL", "https://example.com/whadio/")


def test_reset_command_refuses_invalid_email() -> None:
    # Arrange
    runner = CliRunner()
    # Act
    result = runner.invoke(app, ["links", "password-reset", "--email", "invalid"])
    # Assert
    assert (result.exit_code != 0, "must be an email address" in result.output) == (True, True)


def test_reset_command_requires_a_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.delenv("WHADIO_PUBLIC_URL")
    # Act
    result = CliRunner().invoke(app, ["links", "password-reset", "--email", "alice@example.com"])
    # Assert
    assert (result.exit_code, "WHADIO_PUBLIC_URL" in result.output) == (1, True)


@pytest.mark.slow
@pytest.mark.parametrize("exists", [True, False])
def test_reset_command_issues_redeemable_link_or_refuses_unknown_account(
    database_settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch, *, exists: bool
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_DB_HOST", database_settings.host)
    monkeypatch.setenv("WHADIO_DB_PORT", str(database_settings.port))
    monkeypatch.setenv("WHADIO_DB_NAME", database_settings.name)
    monkeypatch.setenv("WHADIO_DB_APP_PASSWORD", database_settings.app_password.get_secret_value())
    email = f"{uuid4()}@example.com"
    engine = create_engine(database_settings.application_url(), hide_parameters=True)

    async def prepare() -> None:
        database = Database(database_settings)
        try:
            async with database.transaction() as session:
                await AsyncDatabase.add_account(session, "OriginalPassword1", email)
        finally:
            await database.close()

    async def redeem(reset_id: UUID, token: str) -> None:
        database = Database(database_settings)
        try:
            async with database.transaction() as session:
                await PasswordResetService(
                    PasswordResetRepository(session), Argon2PasswordHasher()
                ).complete(reset_id, token, "ReplacementPassword1", datetime.now(UTC))
        finally:
            await database.close()

    try:
        if exists:
            asyncio.run(prepare(), loop_factory=asyncio.SelectorEventLoop)
        # Act
        result = CliRunner().invoke(app, ["links", "password-reset", "--email", email.upper()])
        if not exists:
            assert (result.exit_code, "Account not found" in result.output) == (1, True)
            return
        link = urlsplit(result.stdout.strip())
        reset_id = UUID(link.path.rsplit("/", 1)[1])
        token = parse_qs(link.fragment)["token"][0]
        with engine.connect() as connection:
            stored_hash = connection.scalar(
                select(PasswordReset.token_hash).where(PasswordReset.password_reset_id == reset_id)
            )
        asyncio.run(redeem(reset_id, token), loop_factory=asyncio.SelectorEventLoop)
        # Assert
        assert (result.exit_code, link.scheme, link.netloc, link.path, link.query, stored_hash) == (
            0,
            "https",
            "example.com",
            f"/whadio/password-resets/{reset_id}",
            "",
            hashlib.sha256(token.encode()).hexdigest(),
        )
    finally:
        with engine.begin() as connection:
            connection.execute(delete(User).where(User.email == email))
        engine.dispose()
