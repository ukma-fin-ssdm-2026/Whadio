import asyncio
from collections.abc import Awaitable, Callable, Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Connection, create_engine, delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from whadio.accounts.enums import NotesTemplate, WorkspaceRole
from whadio.accounts.models import User, Workspace, WorkspaceMembership
from whadio.meetings.enums import (
    AccessMode,
    MeetingSource,
    ProcessingState,
    RecordingStatus,
    RevisionType,
)
from whadio.meetings.models import (
    Folder,
    Meeting,
    Speaker,
    Transcript,
    TranscriptRevision,
    TranscriptSegment,
)
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


class AsyncDatabase:
    """Runs a scenario in an async session whose transaction is rolled back afterwards."""

    def __init__(self, settings: DatabaseSettings) -> None:
        self._settings: DatabaseSettings = settings

    def run[T](self, scenario: Callable[[AsyncSession], Awaitable[T]]) -> T:
        async def run() -> T:
            engine = create_async_engine(self._settings.application_url(), hide_parameters=True)
            try:
                async with engine.connect() as connection, connection.begin():
                    async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                        found = await scenario(session)
                    await connection.rollback()
                    return found
            finally:
                await engine.dispose()

        return asyncio.run(run(), loop_factory=asyncio.SelectorEventLoop)

    @staticmethod
    async def add_workspace(session: AsyncSession) -> tuple[UUID, UUID]:
        """Returns the actor and the workspace's default folder, where meetings are added."""
        actor, workspace, folder = uuid4(), uuid4(), uuid4()
        session.add(
            User(
                user_id=actor,
                email=f"{actor}@example.test",
                name="test",
                password_hash=uuid4().hex,
                terms_accepted_at=datetime.now(UTC),
            )
        )
        session.add(
            Workspace(workspace_id=workspace, name="test", default_template=NotesTemplate.SUMMARY)
        )
        await session.flush()
        session.add(
            WorkspaceMembership(workspace_id=workspace, user_id=actor, role=WorkspaceRole.OWNER)
        )
        session.add(
            Folder(folder_id=folder, workspace_id=workspace, name="default", is_default=True)
        )
        await session.flush()
        return actor, folder

    @staticmethod
    async def add_meeting(
        session: AsyncSession,
        place: tuple[UUID, UUID],
        *,
        name_is_generated: bool = True,
        access_mode: AccessMode = AccessMode.WORKSPACE,
        state: ProcessingState = ProcessingState.QUEUED,
    ) -> UUID:
        actor, folder_id = place
        meeting_id = uuid4()
        now = datetime.now(UTC)
        session.add(
            Meeting(
                meeting_id=meeting_id,
                folder_id=folder_id,
                created_by_user_id=actor,
                name="Planning",
                name_is_generated=name_is_generated,
                source_type=MeetingSource.UPLOAD,
                recording_status=RecordingStatus.COMPLETE,
                processing_state=state,
                storage_path=f"meetings/{meeting_id}",
                recorded_at=now,
                recording_delete_after=now + timedelta(days=90),
                access_mode=access_mode,
            )
        )
        await session.flush()
        return meeting_id


@pytest.fixture
def async_database(database_settings: DatabaseSettings) -> AsyncDatabase:
    return AsyncDatabase(database_settings)


@pytest.fixture
def database_connection(database_settings: DatabaseSettings) -> Generator[Connection]:
    engine = create_engine(
        database_settings.application_url(),
        hide_parameters=True,
        connect_args={"connect_timeout": 10},
    )
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                yield connection
            finally:
                if transaction.is_active:
                    transaction.rollback()
    finally:
        engine.dispose()


@pytest.fixture
def database_session(database_connection: Connection) -> Generator[Session]:
    with Session(bind=database_connection, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def committed_workspace(database_settings: DatabaseSettings) -> Generator[tuple[UUID, UUID]]:
    engine = create_engine(database_settings.application_url(), hide_parameters=True)
    actor, workspace = uuid4(), uuid4()
    try:
        with Session(engine) as session, session.begin():
            session.add(
                User(
                    user_id=actor,
                    email=f"{actor}@example.test",
                    name="test",
                    password_hash=uuid4().hex,
                    terms_accepted_at=datetime.now(UTC),
                )
            )
            session.add(
                Workspace(
                    workspace_id=workspace, name="test", default_template=NotesTemplate.SUMMARY
                )
            )
            session.flush()
            session.add(
                WorkspaceMembership(workspace_id=workspace, user_id=actor, role=WorkspaceRole.OWNER)
            )
            session.add(Folder(workspace_id=workspace, name="default", is_default=True))
        yield actor, workspace
    finally:
        with engine.begin() as connection:
            connection.execute(delete(Workspace).where(Workspace.workspace_id == workspace))
            connection.execute(delete(User).where(User.user_id == actor))
        engine.dispose()


@pytest.fixture
def owner_id(database_session: Session) -> UUID:
    user_id = uuid4()
    password_hash = uuid4().hex
    database_session.add(
        User(
            user_id=user_id,
            email=f"{user_id}@example.test",
            name="test",
            password_hash=password_hash,
            terms_accepted_at=datetime.now(UTC),
        )
    )
    database_session.flush()
    return user_id


@pytest.fixture
def workspace_id(database_session: Session, owner_id: UUID) -> UUID:
    workspace = uuid4()
    database_session.add(
        Workspace(workspace_id=workspace, name="test", default_template=NotesTemplate.SUMMARY)
    )
    database_session.flush()
    database_session.add(
        WorkspaceMembership(workspace_id=workspace, user_id=owner_id, role=WorkspaceRole.OWNER)
    )
    database_session.add(Folder(workspace_id=workspace, name="default", is_default=True))
    database_session.flush()
    return workspace


@pytest.fixture
def folder_id(database_session: Session, workspace_id: UUID) -> UUID:
    folder = uuid4()
    database_session.add(Folder(folder_id=folder, workspace_id=workspace_id, name="test"))
    database_session.flush()
    return folder


@pytest.fixture
def other_folder_id(database_session: Session, owner_id: UUID) -> UUID:
    workspace = Workspace(name="other", default_template=NotesTemplate.SUMMARY)
    database_session.add(workspace)
    database_session.flush()
    database_session.add(
        WorkspaceMembership(
            workspace_id=workspace.workspace_id, user_id=owner_id, role=WorkspaceRole.OWNER
        )
    )
    folder = Folder(workspace_id=workspace.workspace_id, name="default", is_default=True)
    database_session.add(folder)
    database_session.flush()
    return folder.folder_id


@pytest.fixture
def meeting_id(database_session: Session, folder_id: UUID, owner_id: UUID) -> UUID:
    meeting = uuid4()
    now = datetime.now(UTC)
    database_session.add(
        Meeting(
            meeting_id=meeting,
            folder_id=folder_id,
            created_by_user_id=owner_id,
            name="test",
            name_is_generated=False,
            source_type=MeetingSource.UPLOAD,
            recording_status=RecordingStatus.COMPLETE,
            processing_state=ProcessingState.QUEUED,
            recorded_at=now,
            recording_delete_after=now + timedelta(days=90),
            access_mode=AccessMode.WORKSPACE,
        )
    )
    database_session.flush()
    return meeting


@pytest.fixture
def revision_id(database_session: Session, meeting_id: UUID) -> UUID:
    transcript = uuid4()
    revision = uuid4()
    database_session.add(
        Transcript(
            transcript_id=transcript,
            meeting_id=meeting_id,
            language="uk",
            model_name="test",
            current_revision_id=revision,
        )
    )
    database_session.flush()
    database_session.add(
        TranscriptRevision(
            revision_id=revision, transcript_id=transcript, revision_type=RevisionType.ORIGINAL
        )
    )
    database_session.flush()
    return revision


@pytest.fixture
def committed_revision_id(
    database_connection: Connection,
    database_session: Session,
    revision_id: UUID,
    workspace_id: UUID,
    owner_id: UUID,
) -> Generator[UUID]:
    database_session.add(Speaker(revision_id=revision_id, display_name="original speaker"))
    database_session.add(
        TranscriptSegment(
            revision_id=revision_id,
            start_time_seconds=Decimal(0),
            end_time_seconds=Decimal(1),
            text="original",
        )
    )
    database_session.flush()
    database_connection.commit()
    try:
        yield revision_id
    finally:
        database_connection.rollback()
        with database_connection.begin():
            database_connection.execute(
                text("DELETE FROM workspace WHERE workspace_id = :id"), {"id": workspace_id}
            )
            database_connection.execute(
                text('DELETE FROM "user" WHERE user_id = :id'), {"id": owner_id}
            )
