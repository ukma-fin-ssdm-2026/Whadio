import asyncio
import hashlib
from collections.abc import Generator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, delete, func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from typer.testing import CliRunner

from conftest import AsyncDatabase

from .accounts.models import PasswordReset, PendingRegistration, User
from .accounts.password_resets import PasswordResetService
from .accounts.passwords import Argon2PasswordHasher
from .accounts.repositories import SessionRepository
from .accounts.reset_repository import PasswordResetRepository
from .cli import app
from .shared.database import Database, DatabaseSettings


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHADIO_PUBLIC_URL", "https://example.com/whadio/")


@pytest.mark.parametrize("command", ["registration", "password-reset"])
def test_link_command_refuses_invalid_email(command: str) -> None:
    # Arrange
    runner = CliRunner()
    # Act
    result = runner.invoke(app, ["links", command, "--email", "invalid"])
    # Assert
    assert (result.exit_code != 0, "must be an email address" in result.output) == (True, True)


@pytest.mark.parametrize("command", ["registration", "password-reset"])
def test_link_command_requires_a_public_url(monkeypatch: pytest.MonkeyPatch, command: str) -> None:
    # Arrange
    monkeypatch.delenv("WHADIO_PUBLIC_URL")
    # Act
    result = CliRunner().invoke(app, ["links", command, "--email", "alice@example.com"])
    # Assert
    assert (result.exit_code, "WHADIO_PUBLIC_URL" in result.output) == (1, True)


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ("registration", "Registration database or configuration unavailable."),
        ("password-reset", "Password-reset database or configuration unavailable."),
    ],
)
def test_link_command_hides_database_errors_and_closes_database(
    monkeypatch: pytest.MonkeyPatch, command: str, message: str
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_DB_APP_PASSWORD", uuid4().hex)
    closed: list[bool] = []
    original_close = Database.close

    def fail_transaction(_database: Database) -> AbstractAsyncContextManager[AsyncSession]:
        raise SQLAlchemyError("private database details")

    async def close(database: Database) -> None:
        await original_close(database)
        closed.append(True)

    monkeypatch.setattr(Database, "transaction", fail_transaction)
    monkeypatch.setattr(Database, "close", close)
    # Act
    result = CliRunner().invoke(app, ["links", command, "--email", "alice@example.com"])
    # Assert
    assert (result.exit_code, result.stdout, result.stderr.strip(), closed) == (
        1,
        "",
        message,
        [True],
    )


@pytest.mark.slow
def test_registration_command_refuses_an_existing_account(
    database_settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_DB_HOST", database_settings.host)
    monkeypatch.setenv("WHADIO_DB_PORT", str(database_settings.port))
    monkeypatch.setenv("WHADIO_DB_NAME", database_settings.name)
    monkeypatch.setenv("WHADIO_DB_APP_PASSWORD", database_settings.app_password.get_secret_value())
    email = f"{uuid4()}@example.com"
    engine = create_engine(database_settings.application_url(), hide_parameters=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(User).values(
                    user_id=uuid4(),
                    email=email,
                    name="Alice",
                    password_hash=uuid4().hex,
                    terms_accepted_at=datetime.now(UTC),
                )
            )
        # Act
        result = CliRunner().invoke(app, ["links", "registration", "--email", email.upper()])
        with engine.connect() as connection:
            pending = connection.scalar(
                select(PendingRegistration.email).where(
                    func.lower(PendingRegistration.email) == email
                )
            )
        # Assert
        assert (result.exit_code, result.stdout, result.stderr.strip(), pending) == (
            1,
            "",
            "An account already exists for this address.",
            None,
        )
    finally:
        with engine.begin() as connection:
            connection.execute(
                delete(PendingRegistration).where(func.lower(PendingRegistration.email) == email)
            )
            connection.execute(delete(User).where(User.email == email))
        engine.dispose()


@pytest.mark.slow
def test_registration_command_prints_a_redeemable_link(
    database_settings: DatabaseSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_DB_HOST", database_settings.host)
    monkeypatch.setenv("WHADIO_DB_PORT", str(database_settings.port))
    monkeypatch.setenv("WHADIO_DB_NAME", database_settings.name)
    monkeypatch.setenv("WHADIO_DB_APP_PASSWORD", database_settings.app_password.get_secret_value())
    email = f"{uuid4()}@example.com"
    engine = create_engine(database_settings.application_url(), hide_parameters=True)
    try:
        # Act
        result = CliRunner().invoke(app, ["links", "registration", "--email", email])
        link = urlsplit(result.stdout.strip())
        with engine.connect() as connection:
            stored = (
                connection.execute(
                    PendingRegistration.__table__.select().where(PendingRegistration.email == email)
                )
                .mappings()
                .one()
            )
        # Assert
        assert (
            result.exit_code,
            link.scheme,
            link.netloc,
            link.path,
            bool(parse_qs(link.fragment).get("token")),
            stored["pending_registration_id"],
        ) == (
            0,
            "https",
            "example.com",
            f"/whadio/registrations/{stored['pending_registration_id']}",
            True,
            UUID(link.path.rsplit("/", 1)[1]),
        )
    finally:
        with engine.begin() as connection:
            connection.execute(
                delete(PendingRegistration).where(PendingRegistration.email == email)
            )
        engine.dispose()


@dataclass(frozen=True)
class StoredAccount:
    engine: Engine
    user_id: UUID
    email: str

    def is_administrator(self) -> bool:
        with self.engine.connect() as connection:
            return bool(
                connection.scalar(select(User.is_administrator).where(User.user_id == self.user_id))
            )

    def set_administrator(self, *, enabled: bool) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(User).where(User.user_id == self.user_id).values(is_administrator=enabled)
            )


@pytest.fixture
def database_environment(
    database_settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch
) -> DatabaseSettings:
    monkeypatch.setenv("WHADIO_DB_HOST", database_settings.host)
    monkeypatch.setenv("WHADIO_DB_PORT", str(database_settings.port))
    monkeypatch.setenv("WHADIO_DB_NAME", database_settings.name)
    monkeypatch.setenv("WHADIO_DB_APP_PASSWORD", database_settings.app_password.get_secret_value())
    return database_settings


@pytest.fixture
def stored_account(database_environment: DatabaseSettings) -> Generator[StoredAccount]:
    engine = create_engine(database_environment.application_url(), hide_parameters=True)
    account = StoredAccount(engine, uuid4(), f"Alice-{uuid4()}@Example.test")
    with engine.begin() as connection:
        connection.execute(
            insert(User).values(
                user_id=account.user_id,
                email=account.email,
                name="Alice",
                password_hash=uuid4().hex,
                terms_accepted_at=datetime.now(UTC),
            )
        )
    try:
        yield account
    finally:
        with engine.begin() as connection:
            connection.execute(delete(User).where(User.user_id == account.user_id))
        engine.dispose()


@pytest.mark.parametrize("command", ["grant", "revoke"])
@pytest.mark.parametrize(
    "options",
    [[], ["--email", "alice@example.com", "--user-id", str(UUID(int=0))]],
    ids=["neither", "both"],
)
def test_admin_commands_require_exactly_one_account_option(
    command: str, options: list[str]
) -> None:
    # Arrange
    runner = CliRunner()
    # Act
    result = runner.invoke(app, ["admin", command, *options])
    # Assert
    assert (result.exit_code, "exactly one" in result.output) == (2, True)


@pytest.mark.slow
@pytest.mark.parametrize(("command", "enabled"), [("grant", True), ("revoke", False)])
def test_admin_commands_ignore_the_case_and_spaces_of_an_email(
    stored_account: StoredAccount, command: str, *, enabled: bool
) -> None:
    # Arrange
    stored_account.set_administrator(enabled=not enabled)
    # Act
    result = CliRunner().invoke(
        app, ["admin", command, "--email", f" {stored_account.email.upper()} "]
    )
    # Assert
    assert (result.exit_code, stored_account.is_administrator()) == (0, enabled)


@pytest.mark.slow
@pytest.mark.parametrize(("command", "enabled"), [("grant", True), ("revoke", False)])
def test_admin_commands_still_accept_a_user_id(
    stored_account: StoredAccount, command: str, *, enabled: bool
) -> None:
    # Arrange
    stored_account.set_administrator(enabled=not enabled)
    # Act
    result = CliRunner().invoke(app, ["admin", command, "--user-id", str(stored_account.user_id)])
    # Assert
    assert (result.exit_code, stored_account.is_administrator()) == (0, enabled)


@pytest.mark.slow
@pytest.mark.usefixtures("database_environment")
@pytest.mark.parametrize("command", ["grant", "revoke"])
@pytest.mark.parametrize(
    "account",
    [["--email", "nobody@example.com"], ["--user-id", str(UUID(int=0))]],
    ids=["email", "user-id"],
)
def test_admin_commands_report_an_unknown_account(command: str, account: list[str]) -> None:
    # Arrange
    runner = CliRunner()
    # Act
    result = runner.invoke(app, ["admin", command, *account])
    # Assert
    assert (result.exit_code, result.stdout, result.stderr.strip()) == (
        1,
        "",
        "Account not found.",
    )


@pytest.mark.slow
def test_password_reset_command_refuses_unknown_account(
    database_settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_DB_HOST", database_settings.host)
    monkeypatch.setenv("WHADIO_DB_PORT", str(database_settings.port))
    monkeypatch.setenv("WHADIO_DB_NAME", database_settings.name)
    monkeypatch.setenv("WHADIO_DB_APP_PASSWORD", database_settings.app_password.get_secret_value())
    email = f"{uuid4()}@example.com"
    # Act
    result = CliRunner().invoke(app, ["links", "password-reset", "--email", email])
    # Assert
    assert (result.exit_code, "Account not found" in result.output) == (1, True)


@pytest.mark.slow
def test_password_reset_command_prints_a_redeemable_link(
    database_settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch
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
                    PasswordResetRepository(session),
                    SessionRepository(session),
                    Argon2PasswordHasher(),
                ).complete(reset_id, token, "ReplacementPassword1", datetime.now(UTC))
        finally:
            await database.close()

    try:
        asyncio.run(prepare(), loop_factory=asyncio.SelectorEventLoop)
        # Act
        result = CliRunner().invoke(app, ["links", "password-reset", "--email", email.upper()])
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
