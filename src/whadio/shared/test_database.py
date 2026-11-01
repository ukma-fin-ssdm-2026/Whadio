from asyncio import Runner, SelectorEventLoop
from io import StringIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr, ValidationError
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from conftest import refused_fields

from .database import ConnectionSettings, Database, DatabaseSettings, MigrationSettings


def test_initial_migration_uses_canonical_audit_action_constraint_name() -> None:
    # Arrange
    output = StringIO()
    config = Config(output_buffer=output)
    config.set_main_option("script_location", "whadio:migrations")
    # Act
    command.upgrade(config, "0001", sql=True)
    # Assert
    assert "ADD CONSTRAINT ck_audit_event_action CHECK" in output.getvalue()


def test_application_url_does_not_expose_password_in_representation() -> None:
    # Arrange
    settings = DatabaseSettings(app_password=SecretStr("test-secret"))
    # Act
    representation = repr(settings.application_url())
    # Assert
    assert "test-secret" not in representation


def test_application_uses_unprivileged_role() -> None:
    # Arrange
    settings = DatabaseSettings(app_password=SecretStr("test-secret"))
    # Act
    username = settings.application_url().username
    # Assert
    assert username == "whadio_app"


def test_migrations_use_owner_role() -> None:
    # Arrange
    settings = MigrationSettings(owner_password=SecretStr("test-secret"))
    # Act
    username = settings.migration_url().username
    # Assert
    assert username == "whadio_owner"


@pytest.fixture
def dotenv_without_passwords(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WHADIO_DB_APP_PASSWORD", raising=False)
    monkeypatch.delenv("WHADIO_DB_OWNER_PASSWORD", raising=False)
    return tmp_path / ".env"


def test_refused_database_settings_do_not_show_the_owner_password(
    dotenv_without_passwords: Path,
) -> None:
    # Arrange
    password = uuid4().hex[:8]
    dotenv_without_passwords.write_text(f"WHADIO_DB_OWNER_PASSWORD={password}\n", encoding="utf-8")
    # Act
    with pytest.raises(ValidationError) as failure:
        DatabaseSettings.model_validate({})
    # Assert
    assert password not in str(failure.value)


def test_refused_migration_settings_do_not_show_the_application_password(
    dotenv_without_passwords: Path,
) -> None:
    # Arrange
    password = uuid4().hex[:8]
    dotenv_without_passwords.write_text(f"WHADIO_DB_APP_PASSWORD={password}\n", encoding="utf-8")
    # Act
    with pytest.raises(ValidationError) as failure:
        MigrationSettings.model_validate({})
    # Assert
    assert password not in str(failure.value)


@pytest.mark.parametrize(
    ("port", "refused"),
    [
        pytest.param(0, {"port"}, id="bva-below-min"),
        pytest.param(1, set[str](), id="bva-min"),
        pytest.param(2, set[str](), id="bva-above-min"),
        pytest.param(5432, set[str](), id="bva-nominal"),
        pytest.param(65534, set[str](), id="bva-below-max"),
        pytest.param(65535, set[str](), id="bva-max"),
        pytest.param(65536, {"port"}, id="bva-above-max"),
    ],
)
def test_database_port_is_accepted_only_from_1_to_65535(port: int, refused: set[str]) -> None:
    # Act
    found = refused_fields(ConnectionSettings, {"port": port})

    # Assert
    assert found == refused


@pytest.mark.slow
@pytest.mark.parametrize(
    "statement",
    ["DELETE FROM audit_event", "UPDATE audit_event SET action = action", "TRUNCATE audit_event"],
)
def test_application_cannot_modify_audit_history(
    database_connection: Connection,
    statement: str,
) -> None:
    # Arrange
    command = text(statement)
    # Act
    with pytest.raises(DBAPIError) as failure:
        database_connection.execute(command)
    # Assert
    assert getattr(failure.value.orig, "sqlstate", None) == "42501"


@pytest.mark.slow
def test_workspace_cannot_commit_without_owner(database_connection: Connection) -> None:
    # Arrange
    database_connection.execute(
        text("INSERT INTO workspace VALUES (:id, 'test', 'summary', now(), false)"), {"id": uuid4()}
    )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    # Assert
    assert "exactly one Owner" in str(failure.value.orig)


@pytest.mark.slow
def test_email_uniqueness_is_case_insensitive(database_connection: Connection) -> None:
    # Arrange
    email = f"{uuid4()}@example.test"
    command = text("INSERT INTO \"user\" VALUES (:id, :email, 'test', 'hash', false, now(), now())")
    database_connection.execute(command, {"id": uuid4(), "email": email})
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_connection.execute(command, {"id": uuid4(), "email": email.upper()})
    # Assert
    assert "uq_user_email" in str(failure.value.orig)


async def _insert_then_fail(database: Database, user: UUID) -> None:
    async with database.transaction() as session:
        await session.execute(
            text("INSERT INTO \"user\" VALUES (:id, :email, 'test', 'hash', false, now(), now())"),
            {"id": user, "email": f"{user}@example.test"},
        )
        raise ValueError("Abort use case")


async def _rollback_transaction(settings: DatabaseSettings) -> bool:
    database = Database(settings)
    user = uuid4()
    try:
        with pytest.raises(ValueError, match="Abort use case"):
            await _insert_then_fail(database, user)
        async with database.transaction() as session:
            result = await session.execute(
                text('SELECT count(*) FROM "user" WHERE user_id = :id'),
                {"id": user},
            )
            return tuple(result.one()) == (0,)
    finally:
        await database.close()


@pytest.mark.slow
def test_database_transaction_rolls_back_on_exception(database_settings: DatabaseSettings) -> None:
    # Arrange
    runner = Runner(loop_factory=SelectorEventLoop)
    # Act
    with runner:
        result = runner.run(_rollback_transaction(database_settings))
    # Assert
    assert result
