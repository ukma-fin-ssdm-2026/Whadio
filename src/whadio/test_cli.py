from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, delete, func, insert, select, update
from typer.testing import CliRunner

from .accounts.models import PendingRegistration, User
from .cli import app
from .shared.database import DatabaseSettings


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHADIO_PUBLIC_URL", "https://example.com/whadio/")


def test_registration_command_refuses_invalid_email() -> None:
    # Arrange
    runner = CliRunner()
    # Act
    result = runner.invoke(app, ["links", "registration", "--email", "invalid"])
    # Assert
    assert (result.exit_code != 0, "must be an email address" in result.output) == (True, True)


def test_registration_command_requires_a_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.delenv("WHADIO_PUBLIC_URL")
    # Act
    result = CliRunner().invoke(app, ["links", "registration", "--email", "alice@example.com"])
    # Assert
    assert (result.exit_code, "WHADIO_PUBLIC_URL" in result.output) == (1, True)


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
