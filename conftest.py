import asyncio
import base64
import hashlib
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ClassVar, Final
from uuid import UUID, uuid4

import httpx
import hypothesis
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field, JsonValue, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Connection, create_engine, delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from whadio.accounts.enums import NotesTemplate, SessionKind, WorkspaceRole
from whadio.accounts.models import Session as SignInSession
from whadio.accounts.models import User, Workspace, WorkspaceMembership
from whadio.accounts.passwords import Argon2PasswordHasher
from whadio.api.app import create_app
from whadio.api.composition import notes_llm, runtime_database, transaction
from whadio.api.core.pagination import ListToken
from whadio.api.settings import WebSettings
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
from whadio.shared.broker import BrokerSettings
from whadio.shared.database import DatabaseSettings
from whadio.shared.notes_llm import NotesLlm, OllamaLlm


class ContinuousIntegrationSettings(BaseSettings):
    ci: bool = Field(
        default=False,
        description="Set by GitHub Actions and most CI services; selects reproducible examples.",
    )


# Hypothesis loads its own "ci" profile whenever CI is set, even to "false", and a profile without
# a parent inherits whatever is loaded; root "dev" in the default profile so it stays random.
hypothesis.settings.register_profile(
    "dev", parent=hypothesis.settings.get_profile("default"), deadline=None
)
hypothesis.settings.load_profile("ci" if ContinuousIntegrationSettings().ci else "dev")


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


BUILT_IN_LLM: Final = OllamaLlm(provider="ollama", model="test-model")


class SavepointTransactions:
    """Each transaction is a savepoint of `session`, which the test rolls back."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        async with self._session.begin_nested():
            yield self._session


# --- Mailpit, the Compose mail catcher ---


class MailpitAddress(BaseModel):
    address: str = Field(alias="Address", description="Email address")


class MailpitMessage(BaseModel):
    message_id: str = Field(alias="ID", description="Mailpit's identifier of the message")
    subject: str = Field(alias="Subject", description="Subject header")
    to: list[MailpitAddress] = Field(alias="To", description="Recipients")


class _MailpitMessages(BaseModel):
    messages: list[MailpitMessage] = Field(description="Most recent messages first")


class _MailpitBody(BaseModel):
    text: str = Field(alias="Text", description="Plain-text body")


class Mailpit(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_file=".env", extra="ignore")

    mailpit_smtp_port: int = Field(
        default=1025, ge=1, le=65535, description="Host port Compose publishes Mailpit's SMTP on"
    )
    mailpit_ui_port: int = Field(
        default=8025, ge=1, le=65535, description="Host port Compose publishes Mailpit's API on"
    )

    def wait_for(self, matches: Callable[[MailpitMessage], bool]) -> MailpitMessage | None:
        deadline = time.monotonic() + 5
        with httpx.Client(base_url=self._api, timeout=2) as client:
            while time.monotonic() < deadline:
                response = client.get("/api/v1/messages")
                response.raise_for_status()
                for message in _MailpitMessages.model_validate_json(response.content).messages:
                    if matches(message):
                        return message
                time.sleep(0.1)
        return None

    def text(self, message: MailpitMessage) -> str:
        response = httpx.get(f"{self._api}/api/v1/message/{message.message_id}", timeout=2)
        response.raise_for_status()
        return _MailpitBody.model_validate_json(response.content).text

    @property
    def _api(self) -> str:
        return f"http://127.0.0.1:{self.mailpit_ui_port}"


def replace_cursor_key(cursor: str, key: str) -> str:
    token = ListToken.model_validate_json(
        base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
    )
    token.key = key
    return base64.urlsafe_b64encode(token.model_dump_json().encode()).decode().rstrip("=")


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
    async def add_account(
        session: AsyncSession, password: str, email: str = "", name: str = "Alice"
    ) -> User:
        user_id = uuid4()
        user = User(
            user_id=user_id,
            # The API refuses special-use domains such as .test, so sign-in needs a real one.
            email=email or f"{user_id}@example.com",
            name=name,
            password_hash=Argon2PasswordHasher().hash(password),
            terms_accepted_at=datetime.now(UTC),
        )
        session.add(user)
        await session.flush()
        return user

    @staticmethod
    async def add_session(
        session: AsyncSession,
        user: User,
        kind: SessionKind,
        expires_in: timedelta = timedelta(days=1),
    ) -> str:
        """A sign-in session for `user`, returning its token; a negative `expires_in` expired."""
        token = uuid4().hex
        now = datetime.now(UTC)
        session.add(
            SignInSession(
                user_id=user.user_id,
                kind=kind,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                created_at=now + expires_in - timedelta(days=1),
                expires_at=now + expires_in,
            )
        )
        await session.flush()
        return token

    @staticmethod
    @asynccontextmanager
    async def api_client(
        session: AsyncSession,
        llm: NotesLlm = BUILT_IN_LLM,
        web_settings: WebSettings | None = None,
    ) -> AsyncGenerator[AsyncClient]:
        """The API, with each request in a savepoint of `session`."""
        app = create_app(web_settings=web_settings)
        app.dependency_overrides[runtime_database] = lambda: SavepointTransactions(session)

        async def savepoint() -> AsyncGenerator[AsyncSession]:
            async with session.begin_nested():
                yield session

        app.dependency_overrides[transaction] = savepoint
        app.dependency_overrides[notes_llm] = lambda: llm
        async with AsyncClient(
            transport=ASGITransport(app), base_url="https://example.test"
        ) as client:
            yield client

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


class BrokerTestSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    broker: BrokerSettings | None = Field(
        default=None, description="Connection to the Compose stack's RabbitMQ"
    )


@pytest.fixture
def rabbitmq_settings() -> BrokerSettings:
    settings = BrokerTestSettings()
    if settings.broker is None:
        pytest.skip("Set WHADIO_BROKER__URL to run RabbitMQ integration tests")
    return settings.broker


NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def refused_fields(model: type[BaseModel], data: Mapping[str, JsonValue]) -> set[str]:
    """Dotted paths of the fields `model` refuses in `data`; empty when it accepts them."""
    try:
        model.model_validate(data)
    except ValidationError as error:
        return {".".join(str(part) for part in detail["loc"]) for detail in error.errors()}
    return set()
