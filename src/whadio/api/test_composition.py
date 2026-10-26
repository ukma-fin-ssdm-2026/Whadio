import asyncio
import hashlib
import wave
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from httpx import ASGITransport, AsyncClient
from pydantic import JsonValue
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from conftest import AsyncDatabase

from ..access_policy.repositories import AccessRepository
from ..access_policy.services import AccessCollaborators, AccessPolicy, AccessService, ContentPath
from ..accounts.contracts import UserProfile
from ..accounts.enums import LlmProvider, NotesTemplate, SessionKind, WorkspaceRole
from ..accounts.models import McpKey, Session, User, Workspace, WorkspaceMembership
from ..accounts.repositories import MembershipRepository, WorkspaceSettingsRepository
from ..accounts.services import WorkspaceSettingsService
from ..audit.contracts import ContentEvent
from ..audit.models import AuditEvent
from ..audit.services import AuditWriter
from ..capture.repositories import CaptureRepository
from ..capture.services import CaptureSpeakerTimeline
from ..meetings.contracts import (
    ContextReference,
    EvictionNotice,
    IEvictionNotifier,
    MeetingFilter,
    QueuedNotes,
)
from ..meetings.enums import (
    AccessMode,
    MeetingSource,
    ProcessingState,
    RecordingStatus,
    RevisionType,
)
from ..meetings.models import (
    Folder,
    Meeting,
    Note,
    NoteContextMeeting,
    RecordingDeletion,
    Speaker,
    Transcript,
    TranscriptRevision,
    TranscriptSegment,
)
from ..meetings.persistence import (
    GeneratedNotes,
    MeetingPersistence,
    PersistenceDependencies,
)
from ..meetings.recordings import RecordingObjects
from ..meetings.repositories import MeetingRepository
from ..meetings.retention import IRetentionMeetings, RetentionMeetings
from ..meetings.services import MeetingService, RecordingInput, TranscriptEdit
from ..notifications.fakes import InMemoryNotificationOutbox
from ..notifications.models import NotificationOutbox
from ..notifications.repositories import notice_payload
from ..notifications.templates import NoticeKind
from ..notifications.templates import ShareAccessRequest as ShareAccessNotice
from ..processing.enums import JobStatus, JobType
from ..processing.models import ProcessingJob
from ..processing.repositories import JobRepository
from ..processing.services import ProcessingCollaborators, ProcessingService
from ..retention.services import RetentionService, StorageUnavailableError
from ..shared.database import Database, DatabaseSettings
from ..shared.errors import Failure, UseCaseError
from ..shared.fakes import InMemoryObjectStorage
from .app import create_app
from .composition import (
    CompositionRoot,
    OutboxShareNotices,
    RuntimeIntegrations,
    folder_service,
    meeting_processing,
    recording_objects,
    share_notifications,
    transaction,
)
from .core.errors import ErrorCode, ErrorResponse
from .mcp_server import build_mcp_server
from .meetings import routes as meeting_routes
from .meetings.schemas import MeetingRead

pytestmark = pytest.mark.slow


def test_multipart_allowance_does_not_relax_file_size_limit(
    database_settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    async def scenario() -> None:
        storage, processing = InMemoryObjectStorage(), ProcessingFixture()
        recording = _wav()
        monkeypatch.setattr(meeting_routes, "MAX_UPLOAD_BYTES", len(recording) - 1)
        async with (
            unit_fixture(database_settings) as unit,
            client_fixture(unit, unit.member, processing, storage) as client,
        ):
            # Act
            response = await client.post(
                f"/api/v1/workspaces/{unit.workspace}/meetings",
                files={"file": ("audio.wav", recording, "audio/wav")},
            )
            error = ErrorResponse.model_validate_json(response.content).error
            # Assert
            assert (
                response.status_code,
                error.code,
                processing.transcriptions,
                storage.objects,
            ) == (
                413,
                ErrorCode.PAYLOAD_TOO_LARGE,
                [],
                {},
            )

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


class FailingContentAuditWriter:
    async def write(self, event: ContentEvent) -> None:
        del event
        raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)


class ProcessingFixture:
    def __init__(self) -> None:
        self.transcriptions: list[UUID] = []
        self.notes: list[tuple[UUID, UUID, NotesTemplate | None, bool]] = []
        self.unavailable: bool = False

    async def queue_transcription(self, meeting_id: UUID) -> None:
        if self.unavailable:
            raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)
        self.transcriptions.append(meeting_id)

    async def queue_notes(
        self,
        meeting_id: UUID,
        requester_id: UUID,
        preset: NotesTemplate | None,
        *,
        use_builtin_model: bool,
        now: datetime,
    ) -> QueuedNotes:
        if self.unavailable:
            raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)
        self.notes.append((meeting_id, requester_id, preset, use_builtin_model))
        return QueuedNotes(
            uuid4(), meeting_id, preset or NotesTemplate.SUMMARY, LlmProvider.WHADIO, now
        )


class EvictionNotices:
    def __init__(self) -> None:
        self.notices: list[EvictionNotice] = []

    async def enqueue(self, notice: EvictionNotice) -> None:
        self.notices.append(notice)


def _wav() -> bytes:
    recording = BytesIO()
    with wave.open(recording, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 800)
    return recording.getvalue()


async def _clean_uploads(settings: DatabaseSettings, storage: InMemoryObjectStorage) -> None:
    database = Database(settings)
    try:
        async with database.transaction() as session:
            for key in storage.uploaded:
                await MeetingRepository(session).release_upload(key)
    finally:
        await database.close()


def test_recording_creation_sets_ninety_day_deadline_and_atomic_audit(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            recorded = datetime(2026, 1, 31, tzinfo=UTC)
            # Act
            created = await unit.meetings.create(
                unit.member,
                unit.workspace,
                RecordingInput("recording/new", recorded, MeetingSource.UPLOAD),
                recorded,
            )
            event = await unit.session.scalar(
                select(AuditEvent).where(AuditEvent.meeting_id == created.meeting_id)
            )
            # Assert
            assert (
                created.folder_id,
                created.recording_delete_after,
                None if event is None else event.action,
            ) == (unit.default_folder, recorded + timedelta(days=90), "meeting_created")

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_extension_recording_without_consent_creates_no_meeting(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            recording = RecordingInput("recording/extension", now, MeetingSource.EXTENSION)
            # Act
            with pytest.raises(UseCaseError) as failure:
                await unit.meetings.create(unit.member, unit.workspace, recording, now)
            meetings = await unit.meetings.list_meetings(unit.member, MeetingFilter(unit.workspace))
            # Assert
            assert (failure.value.code, len(meetings)) == (Failure.VALIDATION_ERROR, 1)

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_extension_recording_preserves_consent_actor_and_time(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            recording = RecordingInput(
                "recording/extension", now, MeetingSource.EXTENSION, consent_confirmed_at=now
            )
            # Act
            created = await unit.meetings.create(unit.member, unit.workspace, recording, now)
            # Assert
            assert (created.consent_confirmed_at, created.consent_confirmed_by_user_id) == (
                now,
                unit.member,
            )

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_move_rejects_folder_from_another_workspace(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            workspace, folder, now = uuid4(), uuid4(), datetime.now(UTC)
            unit.session.add(
                Workspace(
                    workspace_id=workspace,
                    name="other",
                    default_template=NotesTemplate.SUMMARY,
                    created_at=now,
                    is_personal=False,
                )
            )
            await unit.session.flush()
            unit.session.add_all(
                [
                    WorkspaceMembership(
                        workspace_id=workspace,
                        user_id=unit.owner,
                        role=WorkspaceRole.OWNER,
                        joined_at=now,
                    ),
                    Folder(
                        folder_id=folder,
                        workspace_id=workspace,
                        name="default",
                        created_at=now,
                        is_default=True,
                    ),
                ]
            )
            await unit.session.flush()
            # Act
            with pytest.raises(UseCaseError) as failure:
                await unit.meetings.update(unit.owner, unit.meeting, now, folder_id=folder)
            # Assert
            assert failure.value.code == Failure.VALIDATION_ERROR

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_meeting_deletion_preserves_context_snapshot_and_queues_object_cleanup(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            other = await unit.meetings.create(
                unit.owner,
                unit.workspace,
                RecordingInput("recording/other", now, MeetingSource.UPLOAD),
                now,
            )
            note = Note(
                meeting_id=other.meeting_id,
                template=NotesTemplate.SUMMARY,
                content="saved",
                model_name="test",
                provider=LlmProvider.WHADIO,
                created_at=now,
            )
            unit.session.add(note)
            await unit.session.flush()
            snapshot = NoteContextMeeting(
                note_id=note.note_id,
                context_meeting_id=unit.meeting,
                context_meeting_name_snapshot="old name",
            )
            unit.session.add(snapshot)
            await unit.session.flush()
            # Act
            await unit.meetings.delete(unit.owner, unit.meeting, now)
            await unit.session.refresh(snapshot)
            pending = await unit.session.scalar(select(RecordingDeletion.storage_key))
            # Assert
            assert (
                snapshot.context_meeting_id,
                snapshot.context_meeting_name_snapshot,
                pending,
            ) == (None, "old name", "recording/test")

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_requester_profile_is_hidden_from_noncreator(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            share = await unit.access.create_share(unit.owner, unit.meeting, now, redact=False)
            request = await unit.access.request_access(
                unit.outsider, share.share.share_id, share.token, now
            )
            # Act
            with pytest.raises(UseCaseError) as failure:
                await unit.access.requester_profile(unit.member, request.share_access_request_id)
            # Assert
            assert failure.value.code == Failure.INSUFFICIENT_ROLE

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


class RetentionNotices:
    def __init__(self) -> None:
        self.recipients: list[UUID] = []

    async def enqueue(self, meeting_id: UUID, recipient_id: UUID, deadline: datetime) -> None:
        del meeting_id, deadline
        self.recipients.append(recipient_id)


class DeletedKeys:
    def __init__(self) -> None:
        self.keys: list[str] = []
        self.fail: bool = False

    async def delete(self, key: str) -> None:
        if self.fail:
            raise StorageUnavailableError
        self.keys.append(key)


class Notices:
    def __init__(self) -> None:
        self.requests: list[tuple[UUID, UUID, UUID]] = []

    async def enqueue(self, share_id: UUID, creator_id: UUID, requester_id: UUID) -> None:
        self.requests.append((share_id, creator_id, requester_id))


@dataclass(frozen=True)
class Unit:
    session: AsyncSession
    owner: UUID
    member: UUID
    outsider: UUID
    workspace: UUID
    folder: UUID
    default_folder: UUID
    meeting: UUID
    revision: UUID
    speaker: UUID
    segment: UUID
    access: AccessService
    meetings: MeetingService
    database: Database


def persistence_fixture(
    unit: Unit, *, hosted_limit: int | None = None, notifications: IEvictionNotifier | None = None
) -> MeetingPersistence:
    return MeetingPersistence(
        PersistenceDependencies(
            unit.meetings,
            MeetingRepository(unit.session),
            MembershipRepository(unit.session),
            AuditWriter(unit.session),
            unit.access.policy,
            EvictionNotices() if notifications is None else notifications,
        ),
        hosted_limit=hosted_limit,
    )


@asynccontextmanager
async def unit_fixture(settings: DatabaseSettings) -> AsyncGenerator[Unit]:
    database = Database(settings)
    try:
        async with database.sessions() as session, session.begin():
            now = datetime.now(UTC)
            owner, member, outsider = uuid4(), uuid4(), uuid4()
            for user_id in (owner, member, outsider):
                session.add(
                    User(
                        user_id=user_id,
                        email=f"{user_id}@example.test",
                        name="test",
                        password_hash=str(uuid4()),
                        is_administrator=False,
                        terms_accepted_at=now,
                        created_at=now,
                    )
                )
            await session.flush()
            workspace, folder, default_folder = uuid4(), uuid4(), uuid4()
            session.add(
                Workspace(
                    workspace_id=workspace,
                    name="test",
                    default_template=NotesTemplate.SUMMARY,
                    created_at=now,
                    is_personal=False,
                )
            )
            await session.flush()
            for user_id, role in ((owner, WorkspaceRole.OWNER), (member, WorkspaceRole.MEMBER)):
                session.add(
                    WorkspaceMembership(
                        workspace_membership_id=uuid4(),
                        workspace_id=workspace,
                        user_id=user_id,
                        role=role,
                        joined_at=now,
                    )
                )
            session.add_all(
                [
                    Folder(
                        folder_id=folder,
                        workspace_id=workspace,
                        name="test",
                        created_at=now,
                        is_default=False,
                    ),
                    Folder(
                        folder_id=default_folder,
                        workspace_id=workspace,
                        name="default",
                        created_at=now,
                        is_default=True,
                    ),
                ]
            )
            await session.flush()
            meeting, transcript, revision, speaker, segment = (uuid4() for _ in range(5))
            session.add(
                Meeting(
                    meeting_id=meeting,
                    folder_id=folder,
                    created_by_user_id=owner,
                    name="test",
                    name_is_generated=False,
                    source_type=MeetingSource.UPLOAD,
                    recording_status=RecordingStatus.COMPLETE,
                    processing_state=ProcessingState.PROCESSED,
                    storage_path="recording/test",
                    recorded_at=now,
                    created_at=now,
                    recording_delete_after=now + timedelta(days=90),
                    access_mode=AccessMode.WORKSPACE,
                )
            )
            await session.flush()
            session.add(
                Transcript(
                    transcript_id=transcript,
                    meeting_id=meeting,
                    language="uk",
                    model_name="test",
                    created_at=now,
                    current_revision_id=revision,
                )
            )
            await session.flush()
            session.add(
                TranscriptRevision(
                    revision_id=revision,
                    transcript_id=transcript,
                    revision_type=RevisionType.ORIGINAL,
                    created_at=now,
                    edited_by_user_id=None,
                )
            )
            await session.flush()
            session.add(Speaker(speaker_id=speaker, revision_id=revision, display_name="Alice"))
            await session.flush()
            session.add(
                TranscriptSegment(
                    segment_id=segment,
                    revision_id=revision,
                    speaker_id=speaker,
                    start_time_seconds=Decimal(0),
                    end_time_seconds=Decimal(1),
                    text="original",
                )
            )
            session.add(
                Note(
                    note_id=uuid4(),
                    meeting_id=meeting,
                    template=NotesTemplate.SUMMARY,
                    content="Alice will send the report",
                    model_name="test",
                    provider=LlmProvider.WHADIO,
                    created_at=now,
                    created_by_user_id=None,
                )
            )
            await session.flush()
            repository, memberships, audit = (
                AccessRepository(session),
                MembershipRepository(session),
                AuditWriter(session),
            )
            meeting_repository = MeetingRepository(session)
            access = AccessService(
                AccessCollaborators(repository, meeting_repository, memberships, audit, Notices())
            )
            yield Unit(
                session,
                owner,
                member,
                outsider,
                workspace,
                folder,
                default_folder,
                meeting,
                revision,
                speaker,
                segment,
                access,
                MeetingService(meeting_repository, AccessPolicy(repository, memberships), audit),
                database,
            )
            await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            await session.rollback()
    finally:
        await database.close()


@pytest.mark.parametrize("surface", ["meeting", "transcript", "notes"])
def test_content_paths_hide_meetings_from_nonmembers(
    database_settings: DatabaseSettings, surface: str
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            reads = {
                "meeting": unit.meetings.get,
                "transcript": unit.meetings.transcript,
                "notes": unit.meetings.notes,
            }
            # Act
            with pytest.raises(UseCaseError) as failure:
                await reads[surface](unit.outsider, unit.meeting)
            # Assert
            assert failure.value.code == Failure.NOT_FOUND

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_restriction_hides_meeting_even_from_unselected_owner(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            await unit.access.replace_access(
                unit.owner, unit.meeting, {unit.member}, datetime.now(UTC), restricted=True
            )
            # Act
            with pytest.raises(UseCaseError) as failure:
                await unit.meetings.get(unit.owner, unit.meeting)
            # Assert
            assert failure.value.code == Failure.NOT_FOUND

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_member_cannot_manage_restrictions(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            # Act
            with pytest.raises(UseCaseError) as failure:
                await unit.access.replace_access(
                    unit.member, unit.meeting, {unit.member}, datetime.now(UTC), restricted=True
                )
            # Assert
            assert failure.value.code == Failure.INSUFFICIENT_ROLE

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_restriction_and_grants_have_transactional_audit(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            # Act
            await unit.access.replace_access(
                unit.owner,
                unit.meeting,
                {unit.owner, unit.member},
                datetime.now(UTC),
                restricted=True,
            )
            actions = list(
                await unit.session.scalars(
                    select(AuditEvent.action)
                    .where(AuditEvent.meeting_id == unit.meeting)
                    .order_by(AuditEvent.action)
                )
            )
            # Assert
            assert actions == ["access_granted", "access_granted", "meeting_restricted"]

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_invalid_grant_changes_no_access_rows(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            # Act
            with pytest.raises(UseCaseError):
                await unit.access.replace_access(
                    unit.owner, unit.meeting, {unit.outsider}, datetime.now(UTC), restricted=True
                )
            # Assert
            assert (await unit.meetings.get(unit.member, unit.meeting)).access_mode == "workspace"

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_approved_share_is_bound_to_one_account(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            created = await unit.access.create_share(unit.owner, unit.meeting, now, redact=False)
            request = await unit.access.request_access(
                unit.outsider, created.share.share_id, created.token, now
            )
            await unit.access.decide(unit.owner, request.share_access_request_id, now, approve=True)
            # Act
            with pytest.raises(UseCaseError) as failure:
                await unit.access.policy.authorize_share(
                    created.share.share_id, unit.member, ContentPath.READ
                )
            # Assert
            assert failure.value.code == Failure.NOT_FOUND

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


@pytest.mark.parametrize(
    "path", [ContentPath.EXPORT, ContentPath.MCP, ContentPath.RECORDING, ContentPath.WRITE]
)
def test_share_cannot_export_download_use_mcp_or_write(
    database_settings: DatabaseSettings, path: ContentPath
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            created = await unit.access.create_share(unit.owner, unit.meeting, now, redact=False)
            request = await unit.access.request_access(
                unit.outsider, created.share.share_id, created.token, now
            )
            await unit.access.decide(unit.owner, request.share_access_request_id, now, approve=True)
            # Act
            with pytest.raises(UseCaseError) as failure:
                await unit.access.policy.authorize_share(
                    created.share.share_id, unit.outsider, path
                )
            # Assert
            assert failure.value.code == Failure.INSUFFICIENT_ROLE

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_only_share_creator_can_decide_request(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            created = await unit.access.create_share(unit.member, unit.meeting, now, redact=False)
            request = await unit.access.request_access(
                unit.outsider, created.share.share_id, created.token, now
            )
            # Act
            with pytest.raises(UseCaseError) as failure:
                await unit.access.decide(
                    unit.owner, request.share_access_request_id, now, approve=True
                )
            # Assert
            assert failure.value.code == Failure.INSUFFICIENT_ROLE

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_revoked_share_denies_approved_reader(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            created = await unit.access.create_share(unit.owner, unit.meeting, now, redact=False)
            request = await unit.access.request_access(
                unit.outsider, created.share.share_id, created.token, now
            )
            await unit.access.decide(unit.owner, request.share_access_request_id, now, approve=True)
            await unit.access.revoke(unit.owner, created.share.share_id, now)
            # Act
            with pytest.raises(UseCaseError) as failure:
                await unit.meetings.shared_notes(
                    unit.outsider, created.share.share_id, unit.meeting
                )
            # Assert
            assert failure.value.code == Failure.SHARE_REVOKED

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_redacted_notes_replace_known_speaker_names(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            created = await unit.access.create_share(unit.owner, unit.meeting, now, redact=True)
            request = await unit.access.request_access(
                unit.outsider, created.share.share_id, created.token, now
            )
            await unit.access.decide(unit.owner, request.share_access_request_id, now, approve=True)
            # Act
            versions = await unit.meetings.shared_notes(
                unit.outsider, created.share.share_id, unit.meeting
            )
            # Assert
            assert versions[0].note.content == "Speaker 1 will send the report"

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_folder_deletion_preserves_meeting_and_audits_move(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            # Act
            await folder_service(unit.session).delete_folder(
                unit.owner, unit.workspace, unit.folder, datetime.now(UTC)
            )
            meeting = await unit.meetings.get(unit.owner, unit.meeting)
            actions = list(
                await unit.session.scalars(
                    select(AuditEvent.action).where(AuditEvent.meeting_id == unit.meeting)
                )
            )
            # Assert
            assert (meeting.folder_id, meeting.storage_path, actions) == (
                unit.default_folder,
                "recording/test",
                ["meeting_moved"],
            )

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_transcript_edit_preserves_original_and_earlier_revisions(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            # Act
            edited = await unit.meetings.edit_transcript(
                unit.member,
                unit.meeting,
                TranscriptEdit(unit.revision, {unit.segment: "corrected"}, {unit.speaker: "Bob"}),
                datetime.now(UTC),
            )
            original = await unit.meetings.transcript(unit.member, unit.meeting, unit.revision)
            # Assert
            assert (
                original.segments[0].text,
                original.speakers[0].display_name,
                edited.segments[0].text,
                edited.is_edited,
            ) == ("original", "Alice", "corrected", True)

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_stale_transcript_edit_is_refused(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            await unit.meetings.edit_transcript(
                unit.member,
                unit.meeting,
                TranscriptEdit(unit.revision, {unit.segment: "corrected"}, {}),
                datetime.now(UTC),
            )
            # Act
            with pytest.raises(UseCaseError) as failure:
                await unit.meetings.edit_transcript(
                    unit.member,
                    unit.meeting,
                    TranscriptEdit(unit.revision, {unit.segment: "stale"}, {}),
                    datetime.now(UTC),
                )
            # Assert
            assert failure.value.code == Failure.STALE_REVISION

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_restricted_meeting_is_filtered_from_list(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            await unit.access.replace_access(
                unit.owner, unit.meeting, {unit.owner}, datetime.now(UTC), restricted=True
            )
            # Act
            meetings = await unit.meetings.list_meetings(unit.member, MeetingFilter(unit.workspace))
            # Assert
            assert meetings == []

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


async def _browser_token(unit: Unit, user_id: UUID) -> str:
    token = str(uuid4())
    now = datetime.now(UTC)
    unit.session.add(
        Session(
            session_id=uuid4(),
            user_id=user_id,
            kind=SessionKind.BROWSER,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            created_at=now,
            expires_at=now + timedelta(days=14),
        )
    )
    await unit.session.flush()
    return token


@asynccontextmanager
async def client_fixture(
    unit: Unit,
    user_id: UUID,
    processing: ProcessingFixture | None = None,
    storage: InMemoryObjectStorage | None = None,
) -> AsyncGenerator[AsyncClient]:
    app = create_app(unit.database)

    def processing_dependency() -> ProcessingFixture:
        if processing is None:
            raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)
        return processing

    def objects_dependency() -> RecordingObjects:
        if storage is None:
            raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)
        return RecordingObjects(storage)

    if processing is not None:
        app.dependency_overrides[meeting_processing] = processing_dependency
    if storage is not None:
        app.dependency_overrides[recording_objects] = objects_dependency

    async def session_dependency() -> AsyncGenerator[AsyncSession]:
        async with unit.session.begin_nested():
            yield unit.session

    app.dependency_overrides[transaction] = session_dependency

    token = await _browser_token(unit, user_id)
    async with AsyncClient(
        transport=ASGITransport(app),
        base_url="https://example.test",
        headers={"Cookie": f"whadio_session={token}"},
    ) as client:
        yield client


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "/transcript",
        "/transcript/revisions",
        "/notes",
        "/recording",
        "/transcript/export",
        "/notes/export",
    ],
)
def test_http_and_export_paths_hide_restricted_meetings(
    database_settings: DatabaseSettings, suffix: str
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            await unit.access.replace_access(
                unit.owner, unit.meeting, {unit.owner}, datetime.now(UTC), restricted=True
            )
            async with client_fixture(unit, unit.member, storage=InMemoryObjectStorage()) as client:
                # Act
                response = await client.get(f"/api/v1/meetings/{unit.meeting}{suffix}")
                # Assert
                assert (
                    response.status_code,
                    "original" in response.text,
                    "Alice" in response.text,
                ) == (404, False, False)

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_http_member_cannot_create_folder(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with (
            unit_fixture(database_settings) as unit,
            client_fixture(unit, unit.member) as client,
        ):
            # Act
            response = await client.post(
                f"/api/v1/workspaces/{unit.workspace}/folders", json={"name": "new"}
            )
            # Assert
            assert response.status_code == 403

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_http_self_exclusion_commits_restriction(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with (
            unit_fixture(database_settings) as unit,
            client_fixture(unit, unit.owner) as client,
        ):
            # Act
            changed = await client.put(
                f"/api/v1/meetings/{unit.meeting}/access",
                json={"access_mode": "restricted", "member_ids": [str(unit.member)]},
            )
            hidden = await client.get(f"/api/v1/meetings/{unit.meeting}")
            # Assert
            assert (changed.status_code, hidden.status_code) == (200, 404)

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


type ReservedNotice = tuple[UUID, str, NoticeKind, dict[str, JsonValue]]


async def reserved_notices(unit: Unit, *recipients: UUID) -> list[ReservedNotice]:
    rows = await unit.session.execute(
        select(
            NotificationOutbox.recipient_user_id,
            NotificationOutbox.dedupe_key,
            NotificationOutbox.kind,
            NotificationOutbox.payload,
        )
        .where(NotificationOutbox.recipient_user_id.in_(recipients))
        .order_by(NotificationOutbox.dedupe_key)
    )
    return [(recipient, key, kind, payload) for recipient, key, kind, payload in rows]


def test_share_access_request_reserves_a_notice_for_the_share_creator(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            created = await unit.access.create_share(
                unit.owner, unit.meeting, datetime.now(UTC), redact=False
            )
            share_id = created.share.share_id
            async with client_fixture(unit, unit.outsider) as client:
                # Act
                response = await client.post(
                    f"/api/v1/shares/{share_id}/access-requests", json={"token": created.token}
                )
                reserved = await reserved_notices(unit, unit.owner, unit.outsider)
                # Assert
                assert (response.status_code, reserved) == (
                    201,
                    [
                        (
                            unit.owner,
                            f"share_access_request:{share_id}:{unit.outsider}",
                            NoticeKind.SHARE_ACCESS_REQUEST,
                            notice_payload(
                                ShareAccessNotice(
                                    share_id=share_id,
                                    requester_name="test",
                                    requester_email=f"{unit.outsider}@example.test",
                                )
                            ),
                        )
                    ],
                )

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_failed_share_request_rolls_back_its_notice(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            created = await unit.access.create_share(unit.owner, unit.meeting, now, redact=False)
            access = AccessService(
                AccessCollaborators(
                    AccessRepository(unit.session),
                    MeetingRepository(unit.session),
                    MembershipRepository(unit.session),
                    AuditWriter(unit.session),
                    share_notifications(unit.session),
                )
            )

            # Act
            async def request() -> None:
                async with unit.session.begin_nested():
                    await access.request_access(
                        unit.outsider, created.share.share_id, created.token, now
                    )
                    raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)

            with pytest.raises(UseCaseError):
                await request()
            reserved = await reserved_notices(unit, unit.owner)
            # Assert
            assert reserved == []

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_repeated_share_notice_is_reserved_once(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            notices, share_id = share_notifications(unit.session), uuid4()
            await notices.enqueue(share_id, unit.owner, unit.outsider)
            # Act
            await notices.enqueue(share_id, unit.owner, unit.outsider)
            reserved = await reserved_notices(unit, unit.owner)
            # Assert
            assert len(reserved) == 1

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


class NoProfiles:
    async def profile(self, user_id: UUID) -> UserProfile | None:
        del user_id
        return None


def test_share_notice_for_a_requester_without_an_account_is_refused() -> None:
    # Arrange
    outbox = InMemoryNotificationOutbox(lambda: datetime.now(UTC))
    notices = OutboxShareNotices(outbox, NoProfiles())

    # Act
    async def enqueue() -> None:
        await notices.enqueue(uuid4(), uuid4(), uuid4())

    with pytest.raises(UseCaseError) as failure:
        asyncio.run(enqueue())
    # Assert
    assert (failure.value.code, outbox.notices) == (Failure.NOT_FOUND, {})


async def _failed_update(unit: Unit) -> None:
    async with unit.session.begin_nested():
        await unit.meetings.update(unit.member, unit.meeting, datetime.now(UTC), name="changed")
        raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)


def test_failed_change_rolls_back_content_and_audit_together(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            # Act
            with pytest.raises(UseCaseError):
                await _failed_update(unit)
            meeting = await MeetingRepository(unit.session).get(unit.meeting, lock=True)
            actions = list(
                await unit.session.scalars(
                    select(AuditEvent.action).where(AuditEvent.meeting_id == unit.meeting)
                )
            )
            # Assert
            assert (meeting.name, actions) == ("test", [])

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_audit_failure_rolls_back_meeting_change(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            repository = MeetingRepository(unit.session)
            service = MeetingService(repository, unit.access.policy, FailingContentAuditWriter())
            # Act
            with pytest.raises(UseCaseError) as failure:
                async with unit.session.begin_nested():
                    await service.update(
                        unit.member, unit.meeting, datetime.now(UTC), name="changed"
                    )
            meeting = await repository.get(unit.meeting, lock=True)
            # Assert
            assert (failure.value.code, meeting.name) == (
                Failure.INTEGRATION_UNAVAILABLE,
                "test",
            )

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_http_meeting_rename_uses_transactional_audit_writer(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with (
            unit_fixture(database_settings) as unit,
            client_fixture(unit, unit.member) as client,
        ):
            # Act
            response = await client.patch(
                f"/api/v1/meetings/{unit.meeting}", json={"name": "renamed"}
            )
            event = await unit.session.scalar(
                select(AuditEvent).where(AuditEvent.meeting_id == unit.meeting)
            )
            # Assert
            assert (
                response.status_code,
                None if event is None else event.actor_user_id,
                None if event is None else event.action,
                None if event is None else event.details,
            ) == (200, unit.member, "meeting_renamed", None)

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_retention_preserves_transcript_and_notes(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            meeting = await unit.meetings.get(unit.owner, unit.meeting)
            meeting.recording_delete_after = now
            await unit.session.flush()
            notices, storage = RetentionNotices(), DeletedKeys()

            class Transactions:
                @asynccontextmanager
                async def transaction(self) -> AsyncGenerator[IRetentionMeetings]:
                    async with unit.session.begin_nested():
                        yield RetentionMeetings(unit.session, unit.access.policy, notices)

            # Act
            result = await RetentionService(Transactions(), storage).run(now)
            transcript = await unit.meetings.transcript(unit.member, unit.meeting)
            notes = await unit.meetings.notes(unit.member, unit.meeting)
            # Assert
            assert (
                result.deleted,
                transcript.segments[0].text,
                notes[0].note.content,
                meeting.storage_path,
            ) == ([unit.meeting], "original", "Alice will send the report", None)

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_successful_regeneration_preserves_previous_notes_and_audits_requester(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            workflows = persistence_fixture(unit)
            # Act
            await workflows.save_generated_notes(
                unit.meeting,
                GeneratedNotes(
                    NotesTemplate.SUMMARY, LlmProvider.WHADIO, "model", "new notes", "generated", ()
                ),
                unit.member,
                datetime.now(UTC),
            )
            versions = await unit.meetings.notes(unit.member, unit.meeting)
            event = await unit.session.scalar(
                select(AuditEvent).where(AuditEvent.meeting_id == unit.meeting)
            )
            # Assert
            assert (
                len(versions),
                {v.note.content for v in versions},
                None
                if event is None
                else (event.actor_user_id, event.action, event.details, event.subject_id),
            ) == (
                2,
                {"new notes", "Alice will send the report"},
                (unit.member, "notes_regenerated", {"preset": "summary"}, None),
            )

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_deleted_context_retains_snapshot_in_generated_notes(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            # Act
            await persistence_fixture(unit).save_generated_notes(
                unit.meeting,
                GeneratedNotes(
                    NotesTemplate.SUMMARY,
                    LlmProvider.WHADIO,
                    "model",
                    "new notes",
                    "generated",
                    (ContextReference(uuid4(), "deleted context"),),
                ),
                None,
                datetime.now(UTC),
            )
            versions = await unit.meetings.notes(unit.member, unit.meeting)
            references = [item for version in versions for item in version.context]
            # Assert
            assert [
                (r.context_meeting_id, r.context_meeting_name_snapshot) for r in references
            ] == [(None, "deleted context")]

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_hosted_ingest_evicts_oldest_and_reserves_transcription(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            processing = ProcessingFixture()
            workflows = persistence_fixture(unit, hosted_limit=1)
            now = datetime.now(UTC)
            # Act
            await workflows.ingest(
                unit.member,
                unit.workspace,
                RecordingInput("recording/new", now, MeetingSource.UPLOAD),
                now,
            )
            actions = list(
                await unit.session.scalars(
                    select(AuditEvent.action).where(AuditEvent.meeting_id == unit.meeting)
                )
            )
            cleanup = await unit.session.scalar(select(RecordingDeletion.storage_key))
            # Assert
            assert (processing.transcriptions, actions, cleanup) == (
                [],
                ["meeting_evicted"],
                "recording/test",
            )

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_failed_ingest_rolls_back_eviction_and_cleanup(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            processing = ProcessingFixture()
            processing.unavailable = True
            now = datetime.now(UTC)

            # Act
            async def ingest() -> None:
                async with unit.session.begin_nested():
                    meeting = await persistence_fixture(unit, hosted_limit=1).ingest(
                        unit.member,
                        unit.workspace,
                        RecordingInput("recording/new", now, MeetingSource.UPLOAD),
                        now,
                    )
                    await processing.queue_transcription(meeting.meeting_id)

            with pytest.raises(UseCaseError):
                await ingest()
            original = await unit.meetings.get(unit.member, unit.meeting)
            cleanup = await unit.session.scalar(select(RecordingDeletion.deletion_id))
            # Assert
            assert (original.storage_path, cleanup) == ("recording/test", None)

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_open_capture_does_not_count_towards_hosted_capacity(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            original = await unit.meetings.get(unit.owner, unit.meeting)
            original.processing_state = ProcessingState.RECORDING
            now = datetime.now(UTC)
            # Act
            await persistence_fixture(unit, hosted_limit=1).ingest(
                unit.member,
                unit.workspace,
                RecordingInput("recording/new", now, MeetingSource.UPLOAD),
                now,
            )
            original = await unit.meetings.get(unit.owner, unit.meeting)
            # Assert
            assert original.processing_state == ProcessingState.RECORDING

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


@pytest.mark.parametrize("valid", [True, False])
def test_upload_decodes_audio_before_creating_meeting(
    database_settings: DatabaseSettings, *, valid: bool
) -> None:
    # Arrange
    async def scenario() -> None:
        storage, processing = InMemoryObjectStorage(), ProcessingFixture()
        try:
            async with (
                unit_fixture(database_settings) as unit,
                client_fixture(unit, unit.member, processing, storage) as client,
            ):
                # Act
                response = await client.post(
                    f"/api/v1/workspaces/{unit.workspace}/meetings",
                    files={
                        "file": (
                            "audio.mp3",
                            _wav() if valid else b"not audio",
                            "application/octet-stream",
                        )
                    },
                )
                # Assert
                assert (
                    response.status_code,
                    len(processing.transcriptions),
                    len(storage.objects),
                    "Location" in response.headers,
                ) == ((201, 1, 1, True) if valid else (415, 0, 0, False))
        finally:
            await _clean_uploads(database_settings, storage)

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


@pytest.mark.parametrize("cleanup_succeeds", [True, False])
def test_failed_upload_keeps_durable_cleanup_when_storage_is_unavailable(
    database_settings: DatabaseSettings,
    *,
    cleanup_succeeds: bool,
) -> None:
    # Arrange
    async def scenario() -> None:
        storage, processing = InMemoryObjectStorage(), ProcessingFixture()
        processing.unavailable = True
        storage.fail_delete = not cleanup_succeeds
        try:
            async with (
                unit_fixture(database_settings) as unit,
                client_fixture(unit, unit.member, processing, storage) as client,
            ):
                # Act
                response = await client.post(
                    f"/api/v1/workspaces/{unit.workspace}/meetings",
                    files={"file": ("audio.wav", _wav())},
                )
                pending = await unit.session.scalar(
                    select(RecordingDeletion.storage_key).where(
                        RecordingDeletion.storage_key.in_(storage.uploaded)
                    )
                )
                # Assert
                assert (
                    response.status_code,
                    len(storage.objects),
                    pending in storage.uploaded,
                ) == (
                    503,
                    0 if cleanup_succeeds else 1,
                    True,
                )
        finally:
            await _clean_uploads(database_settings, storage)

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_http_regeneration_is_unavailable(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        processing = ProcessingFixture()
        async with (
            unit_fixture(database_settings) as unit,
            client_fixture(unit, unit.member, processing) as client,
        ):
            # Act
            response = await client.post(f"/api/v1/meetings/{unit.meeting}/notes")
            error = ErrorResponse.model_validate_json(response.content).error
            # Assert
            assert (response.status_code, error.code, processing.notes) == (
                503,
                ErrorCode.INTEGRATION_UNAVAILABLE,
                [],
            )

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_http_regeneration_hides_a_meeting_the_caller_cannot_read(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with (
            unit_fixture(database_settings) as unit,
            client_fixture(unit, unit.outsider) as client,
        ):
            # Act
            response = await client.post(f"/api/v1/meetings/{unit.meeting}/notes")
            # Assert
            assert response.status_code == 404

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_retention_warns_only_selected_current_members(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            await unit.access.replace_access(
                unit.owner, unit.meeting, {unit.member}, now, restricted=True
            )
            meeting = await MeetingRepository(unit.session).get(unit.meeting)
            meeting.recording_delete_after = now + timedelta(days=7)
            await unit.session.flush()
            notices = RetentionNotices()

            class Transactions:
                @asynccontextmanager
                async def transaction(self) -> AsyncGenerator[IRetentionMeetings]:
                    async with unit.session.begin_nested():
                        yield RetentionMeetings(unit.session, unit.access.policy, notices)

            # Act
            await RetentionService(Transactions(), DeletedKeys()).run(now)
            # Assert
            assert notices.recipients == [unit.member]

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_deleted_meeting_cleanup_survives_storage_failure_and_retries(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            await unit.meetings.delete(unit.owner, unit.meeting, datetime.now(UTC))
            notices, keys = RetentionNotices(), DeletedKeys()

            class Transactions:
                @asynccontextmanager
                async def transaction(self) -> AsyncGenerator[IRetentionMeetings]:
                    async with unit.session.begin_nested():
                        yield RetentionMeetings(unit.session, unit.access.policy, notices)

            service = RetentionService(Transactions(), keys)
            keys.fail = True
            # Act
            failed = await service.remove_deleted_meeting_recordings()
            keys.fail = False
            retried = await service.remove_deleted_meeting_recordings()
            repeated = await service.remove_deleted_meeting_recordings()
            pending = list(await unit.session.scalars(select(RecordingDeletion)))
            # Assert
            assert (len(failed), retried, repeated, pending, keys.keys) == (
                1,
                [],
                [],
                [],
                ["recording/test"],
            )

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_mcp_tool_hides_restricted_meeting_from_key_owner(
    database_settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now, token = datetime.now(UTC), str(uuid4())
            unit.session.add(
                McpKey(
                    mcp_key_id=uuid4(),
                    user_id=unit.member,
                    key_hash=hashlib.sha256(token.encode()).hexdigest(),
                    created_at=now,
                    expires_at=None,
                    revoked_at=None,
                )
            )
            await unit.session.flush()
            await unit.access.replace_access(
                unit.owner, unit.meeting, {unit.owner}, now, restricted=True
            )
            request = Request(
                {"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]}
            )
            monkeypatch.setattr("whadio.api.mcp_server.get_http_request", lambda: request)

            class Transactions:
                @asynccontextmanager
                async def transaction(self) -> AsyncGenerator[AsyncSession]:
                    async with unit.session.begin_nested():
                        yield unit.session

            async with Client(build_mcp_server(Transactions)) as client:
                # Act
                with pytest.raises(ToolError, match="NOT_FOUND"):
                    await client.call_tool("get_transcript", {"meeting_id": str(unit.meeting)})
                # Assert
                assert (await client.call_tool("list_meetings")).content == []

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_mcp_rejects_revoked_key(
    database_settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now, token = datetime.now(UTC), str(uuid4())
            unit.session.add(
                McpKey(
                    mcp_key_id=uuid4(),
                    user_id=unit.member,
                    key_hash=hashlib.sha256(token.encode()).hexdigest(),
                    created_at=now,
                    expires_at=None,
                    revoked_at=now,
                )
            )
            await unit.session.flush()
            request = Request(
                {"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]}
            )
            monkeypatch.setattr("whadio.api.mcp_server.get_http_request", lambda: request)

            class Transactions:
                @asynccontextmanager
                async def transaction(self) -> AsyncGenerator[AsyncSession]:
                    async with unit.session.begin_nested():
                        yield unit.session

            async with Client(build_mcp_server(Transactions)) as client:
                # Act
                with pytest.raises(ToolError, match="Authentication required") as failure:
                    await client.call_tool("get_notes", {"meeting_id": str(unit.meeting)})
                # Assert
                assert "Alice" not in str(failure.value)

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


# --- Queueing transcription for an upload ---


def test_upload_is_unavailable_without_a_broker(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        meeting_id = await AsyncDatabase.add_meeting(
            session, await AsyncDatabase.add_workspace(session)
        )
        # Act
        try:
            await CompositionRoot().processing(session).queue_transcription(meeting_id)
        except UseCaseError as error:
            return error.code
        return None

    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.INTEGRATION_UNAVAILABLE


def test_upload_queues_a_transcription_job_to_publish(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        storage = InMemoryObjectStorage()
        try:
            async with unit_fixture(database_settings) as unit:
                app = create_app(
                    unit.database,
                    integrations=RuntimeIntegrations(
                        processing=lambda _session: ProcessingService(
                            ProcessingCollaborators(
                                JobRepository(unit.session),
                                unit.meetings,
                                persistence_fixture(unit),
                                WorkspaceSettingsService(WorkspaceSettingsRepository(unit.session)),
                                storage,
                                CaptureSpeakerTimeline(CaptureRepository(unit.session)),
                            )
                        )
                    ),
                )
                app.dependency_overrides[recording_objects] = lambda: RecordingObjects(storage)

                async def savepoint() -> AsyncGenerator[AsyncSession]:
                    async with unit.session.begin_nested():
                        yield unit.session

                app.dependency_overrides[transaction] = savepoint
                token = await _browser_token(unit, unit.member)
                async with AsyncClient(
                    transport=ASGITransport(app),
                    base_url="https://example.test",
                    headers={"Cookie": f"whadio_session={token}"},
                ) as client:
                    # Act
                    response = await client.post(
                        f"/api/v1/workspaces/{unit.workspace}/meetings",
                        files={"file": ("audio.wav", _wav(), "audio/wav")},
                    )
                meeting_id = MeetingRead.model_validate_json(response.content).id
                jobs = await unit.session.execute(
                    select(
                        ProcessingJob.job_type, ProcessingJob.status, ProcessingJob.published_at
                    ).where(ProcessingJob.meeting_id == meeting_id)
                )
                # Assert
                assert [tuple(job) for job in jobs] == [
                    (JobType.TRANSCRIPTION, JobStatus.QUEUED, None)
                ]
        finally:
            await _clean_uploads(database_settings, storage)

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
