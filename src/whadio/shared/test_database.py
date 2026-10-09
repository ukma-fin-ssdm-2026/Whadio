from asyncio import Runner, SelectorEventLoop
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from .database import Database, DatabaseSettings, MigrationSettings


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
