from collections.abc import Generator
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import make_url

from whadio.shared.database import DatabaseSettings


class DatabaseTestSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="WHADIO_TEST_")

    database_url: SecretStr | None = Field(
        default=None,
        description="Application-role URL for a migrated, disposable PostgreSQL database.",
    )


@pytest.fixture
def database_settings() -> DatabaseSettings:
    settings = DatabaseTestSettings()
    if settings.database_url is None:
        pytest.skip("Set WHADIO_TEST_DATABASE_URL to run PostgreSQL integration tests")
    url = make_url(settings.database_url.get_secret_value())
    if url.username != "whadio_app" or url.password is None:
        pytest.fail("Database tests require the whadio_app role and its password")
    return DatabaseSettings(
        host=url.host or "localhost",
        port=url.port or 5432,
        name=url.database or "whadio",
        app_password=SecretStr(url.password),
    )


@pytest.fixture
def database_connection() -> Generator[Connection]:
    settings = DatabaseTestSettings()
    if settings.database_url is None:
        pytest.skip("Set WHADIO_TEST_DATABASE_URL to run PostgreSQL integration tests")
    engine = create_engine(settings.database_url.get_secret_value(), hide_parameters=True)
    try:
        with engine.connect() as connection, connection.begin() as transaction:
            yield connection
            transaction.rollback()
    finally:
        engine.dispose()


@pytest.fixture
def owner_id(database_connection: Connection) -> UUID:
    user_id = uuid4()
    database_connection.execute(
        text("INSERT INTO \"user\" VALUES (:id, :email, 'test', 'hash', false, now(), now())"),
        {"id": user_id, "email": f"{user_id}@example.test"},
    )
    return user_id


@pytest.fixture
def workspace_id(database_connection: Connection, owner_id: UUID) -> UUID:
    workspace = uuid4()
    database_connection.execute(
        text("INSERT INTO workspace VALUES (:id, 'test', 'summary', now(), false)"),
        {"id": workspace},
    )
    database_connection.execute(
        text("INSERT INTO workspace_membership VALUES (:id, :workspace, :user, 'Owner', now())"),
        {"id": uuid4(), "workspace": workspace, "user": owner_id},
    )
    database_connection.execute(
        text("INSERT INTO folder VALUES (:id, :workspace, 'default', now(), true)"),
        {"id": uuid4(), "workspace": workspace},
    )
    return workspace


@pytest.fixture
def folder_id(database_connection: Connection, workspace_id: UUID) -> UUID:
    folder = uuid4()
    database_connection.execute(
        text("INSERT INTO folder VALUES (:id, :workspace, 'test', now(), false)"),
        {"id": folder, "workspace": workspace_id},
    )
    return folder


@pytest.fixture
def meeting_id(database_connection: Connection, folder_id: UUID, owner_id: UUID) -> UUID:
    meeting = uuid4()
    database_connection.execute(
        text("""
            INSERT INTO meeting (
                meeting_id, folder_id, created_by_user_id, name, name_is_generated,
                source_type, recording_status, processing_state, recorded_at, created_at,
                recording_delete_after, access_mode
            ) VALUES (:id, :folder, :user, 'test', false, 'upload', 'complete', 'queued',
                      now(), now(), now() + interval '90 days', 'workspace')
        """),
        {"id": meeting, "folder": folder_id, "user": owner_id},
    )
    return meeting


@pytest.fixture
def revision_id(database_connection: Connection, meeting_id: UUID) -> UUID:
    transcript = uuid4()
    revision = uuid4()
    database_connection.execute(
        text("INSERT INTO transcript VALUES (:id, :meeting, 'uk', 'test', now(), :revision)"),
        {"id": transcript, "meeting": meeting_id, "revision": revision},
    )
    database_connection.execute(
        text("INSERT INTO transcript_revision VALUES (:id, :transcript, 'original', NULL, now())"),
        {"id": revision, "transcript": transcript},
    )
    return revision
