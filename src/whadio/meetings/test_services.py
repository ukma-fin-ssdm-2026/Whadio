import asyncio
from collections.abc import AsyncGenerator, Awaitable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from conftest import AsyncDatabase

from ..access_policy.models import ExternalShare, MeetingAccessGrant
from ..access_policy.repositories import AccessRepository
from ..access_policy.services import AccessPolicy
from ..accounts.enums import LlmProvider, NotesTemplate, WorkspaceRole
from ..accounts.models import User, Workspace, WorkspaceMembership
from ..accounts.repositories import MembershipRepository
from ..accounts.services import WorkspaceMembershipService
from ..audit.enums import AuditAction
from ..audit.models import AuditEvent
from ..audit.services import AuditWriter, MeetingMoved
from ..shared.database import DatabaseSettings
from ..shared.errors import Failure, UseCaseError
from .contracts import InitialSegment, InitialSpeaker, InitialTranscript, ProcessingUpdate
from .enums import AccessMode, MeetingSource, ProcessingState, RecordingStatus
from .models import Folder, GlossaryTerm, Meeting, Note
from .repositories import FolderRepository, MeetingRepository
from .services import (
    FolderService,
    MeetingService,
    RecordingInput,
    TermUpdate,
    TranscriptEdit,
    WorkspaceContent,
)


@asynccontextmanager
async def folder_session(settings: DatabaseSettings) -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine(settings.application_url(), hide_parameters=True)
    try:
        async with engine.connect() as connection, connection.begin():
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                yield session
            await connection.rollback()
    finally:
        await engine.dispose()


async def populate_folder(session: AsyncSession) -> tuple[UUID, UUID, UUID, UUID, list[UUID]]:
    actor, workspace, source, destination = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    session.add(
        User(
            user_id=actor,
            email=f"{actor}@example.test",
            name="test",
            password_hash=uuid4().hex,
            terms_accepted_at=now,
        )
    )
    session.add(
        Workspace(workspace_id=workspace, name="test", default_template=NotesTemplate.SUMMARY)
    )
    await session.flush()
    session.add(
        WorkspaceMembership(workspace_id=workspace, user_id=actor, role=WorkspaceRole.OWNER)
    )
    session.add_all(
        [
            Folder(folder_id=source, workspace_id=workspace, name="source"),
            Folder(folder_id=destination, workspace_id=workspace, name="default", is_default=True),
        ]
    )
    await session.flush()
    meetings = [uuid4(), uuid4()]
    for meeting_id in meetings:
        session.add(
            Meeting(
                meeting_id=meeting_id,
                folder_id=source,
                created_by_user_id=actor,
                name="test",
                name_is_generated=False,
                source_type=MeetingSource.UPLOAD,
                recording_status=RecordingStatus.COMPLETE,
                processing_state=ProcessingState.QUEUED,
                access_mode=AccessMode.RESTRICTED,
                recorded_at=now,
                recording_delete_after=now + timedelta(days=90),
            )
        )
    await session.flush()
    for meeting_id in meetings:
        session.add(
            MeetingAccessGrant(meeting_id=meeting_id, user_id=actor, granted_by_user_id=actor)
        )
    await session.flush()
    return actor, workspace, source, destination, meetings


@dataclass(frozen=True)
class AuditState:
    actor_id: UUID
    action: AuditAction
    workspace_id: UUID | None
    meeting_id: UUID | None
    occurred_at: datetime
    details: JsonValue | None


@dataclass(frozen=True)
class FolderState:
    source_exists: bool
    locations: tuple[UUID, ...]
    grants: frozenset[UUID]
    events: tuple[AuditState, ...]


@dataclass(frozen=True)
class RollbackState:
    source_exists: bool
    locations: tuple[UUID, ...]
    event_count: int


@pytest.mark.slow
def test_folder_deletion_audits_each_move_and_preserves_restricted_grants(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> tuple[FolderState, FolderState]:
        async with folder_session(database_settings) as session:
            actor, workspace, source, destination, meetings = await populate_folder(session)
            service = FolderService(
                FolderRepository(session),
                WorkspaceMembershipService(MembershipRepository(session)),
                AuditWriter(session),
            )
            now = datetime.now(UTC)
            await service.delete_folder(actor, workspace, source, now)
            await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            events = list(
                await session.scalars(
                    select(AuditEvent).where(AuditEvent.workspace_id == workspace)
                )
            )
            grants = list(
                await session.scalars(
                    select(MeetingAccessGrant.meeting_id).where(
                        MeetingAccessGrant.meeting_id.in_(meetings)
                    )
                )
            )
            locations = list(
                await session.scalars(
                    select(Meeting.folder_id).where(Meeting.meeting_id.in_(meetings))
                )
            )
            observed = FolderState(
                source_exists=await session.get(Folder, source) is not None,
                locations=tuple(locations),
                grants=frozenset(grants),
                events=tuple(
                    AuditState(
                        event.actor_user_id,
                        event.action,
                        event.workspace_id,
                        event.meeting_id,
                        event.occurred_at,
                        event.details,
                    )
                    for event in sorted(events, key=lambda event: str(event.meeting_id))
                ),
            )
            expected = FolderState(
                source_exists=False,
                locations=(destination, destination),
                grants=frozenset(meetings),
                events=tuple(
                    AuditState(
                        actor,
                        AuditAction.MEETING_MOVED,
                        workspace,
                        meeting_id,
                        now,
                        {"from_folder_id": str(source), "to_folder_id": str(destination)},
                    )
                    for meeting_id in sorted(meetings, key=str)
                ),
            )
            return observed, expected

    # Act
    observed, expected = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert observed == expected


class FailingAuditWriter:
    def __init__(self, session: AsyncSession) -> None:
        self._writer: AuditWriter = AuditWriter(session)
        self._written: bool = False

    async def write(self, event: MeetingMoved) -> None:
        if self._written:
            raise RuntimeError("Audit unavailable")
        await self._writer.write(event)
        self._written = True


@pytest.mark.slow
def test_audit_failure_rolls_back_folder_moves_and_previous_events(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> tuple[RollbackState, RollbackState]:
        async with folder_session(database_settings) as session:
            actor, workspace, source, _, meetings = await populate_folder(session)
            service = FolderService(
                FolderRepository(session),
                WorkspaceMembershipService(MembershipRepository(session)),
                FailingAuditWriter(session),
            )
            with pytest.raises(RuntimeError, match="Audit unavailable"):
                async with session.begin_nested():
                    await service.delete_folder(actor, workspace, source, datetime.now(UTC))
            locations = list(
                await session.scalars(
                    select(Meeting.folder_id).where(Meeting.meeting_id.in_(meetings))
                )
            )
            events = list(
                await session.scalars(
                    select(AuditEvent).where(AuditEvent.workspace_id == workspace)
                )
            )
            return (
                RollbackState(
                    source_exists=await session.get(Folder, source) is not None,
                    locations=tuple(locations),
                    event_count=len(events),
                ),
                RollbackState(source_exists=True, locations=(source, source), event_count=0),
            )

    # Act
    observed, expected = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert observed == expected


# --- For Processing ---


def pipeline_service(session: AsyncSession) -> MeetingService:
    memberships = WorkspaceMembershipService(MembershipRepository(session))
    return MeetingService(
        MeetingRepository(session),
        AccessPolicy(AccessRepository(session), memberships),
        AuditWriter(session),
    )


async def transcribed(session: AsyncSession, meeting_id: UUID) -> None:
    await pipeline_service(session).save_initial_transcript(
        meeting_id,
        InitialTranscript(
            job_id=uuid4(),
            language="uk",
            model_name="parakeet",
            speakers=(InitialSpeaker("Speaker 1", "Speaker 1"),),
            segments=(InitialSegment("Speaker 1", Decimal(0), Decimal(1), "Привіт"),),
        ),
        datetime.now(UTC),
    )


@pytest.mark.slow
def test_notes_context_holds_only_processed_open_meetings_of_the_folder(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[list[UUID], UUID]:
        place = await AsyncDatabase.add_workspace(session)
        meeting = await AsyncDatabase.add_meeting(session, place, state=ProcessingState.PROCESSED)
        context = await AsyncDatabase.add_meeting(session, place, state=ProcessingState.PROCESSED)
        restricted = await AsyncDatabase.add_meeting(
            session, place, state=ProcessingState.PROCESSED, access_mode=AccessMode.RESTRICTED
        )
        queued = await AsyncDatabase.add_meeting(session, place)
        for transcribed_id in (meeting, context, restricted, queued):
            await transcribed(session, transcribed_id)
        service = pipeline_service(session)
        target = await service.pipeline_meeting(meeting)
        assert target is not None
        # Act
        found = await service.notes_context(target.meeting, 5)
        return [other.meeting.meeting_id for other in found], context

    found, context = async_database.run(scenario)
    # Assert
    assert found == [context]


@pytest.mark.slow
def test_pipeline_meeting_of_a_deleted_meeting_is_none(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        # Act
        found = await pipeline_service(session).pipeline_meeting(uuid4())
        return found is None

    missing = async_database.run(scenario)
    # Assert
    assert missing


@pytest.mark.slow
def test_processing_update_records_the_duration(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int | None:
        meeting_id = await AsyncDatabase.add_meeting(
            session, await AsyncDatabase.add_workspace(session)
        )
        # Act
        await pipeline_service(session).save_processing_state(
            meeting_id, ProcessingUpdate(ProcessingState.PROCESSING, duration_seconds=62)
        )
        return await session.scalar(
            select(Meeting.duration_seconds).where(Meeting.meeting_id == meeting_id)
        )

    duration = async_database.run(scenario)
    # Assert
    assert duration == 62


@pytest.mark.slow
def test_failed_state_needs_a_failure_reason(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        return await refusal(
            unit.service.save_processing_state(
                unit.meeting, ProcessingUpdate(ProcessingState.FAILED)
            )
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.VALIDATION_ERROR


@pytest.mark.slow
def test_processing_update_records_the_regeneration_count(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        unit = await team(session)
        await unit.service.save_processing_state(
            unit.meeting, ProcessingUpdate(ProcessingState.PROCESSED, regeneration_count=2)
        )
        return (await unit.service.get(unit.owner, unit.meeting)).regeneration_count

    # Act
    count = async_database.run(scenario)
    # Assert
    assert count == 2


@pytest.mark.slow
def test_replaying_the_transcription_job_keeps_the_saved_revision(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        unit = await team(session)
        first = await unit.service.save_initial_transcript(unit.meeting, ALICE, NOW)
        replayed = await unit.service.save_initial_transcript(unit.meeting, ALICE, NOW)
        return replayed.revision.revision_id == first.revision.revision_id

    # Act
    kept = async_database.run(scenario)
    # Assert
    assert kept


@pytest.mark.slow
def test_another_job_cannot_replace_the_transcript(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        await unit.service.save_initial_transcript(unit.meeting, ALICE, NOW)
        return await refusal(
            unit.service.save_initial_transcript(unit.meeting, replace(ALICE, job_id=uuid4()), NOW)
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.TRANSCRIPT_EXISTS


@pytest.mark.slow
def test_current_transcript_of_an_untranscribed_meeting_is_none(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        unit = await team(session)
        return await unit.service.current_transcript(unit.meeting) is None

    # Act
    missing = async_database.run(scenario)
    # Assert
    assert missing


@pytest.mark.slow
def test_processing_snapshot_hides_the_meeting_from_nonmembers(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        return await refusal(unit.service.processing_snapshot(unit.outsider, unit.meeting))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.NOT_FOUND


@pytest.mark.slow
def test_removing_workspace_content_deletes_its_meetings(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        await WorkspaceContent(MeetingRepository(session)).remove_meetings(unit.workspace, NOW)
        return await refusal(unit.service.get(unit.owner, unit.meeting))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.NOT_FOUND


# --- For members ---

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
ALICE = InitialTranscript(
    job_id=uuid4(),
    language="uk",
    model_name="parakeet",
    speakers=(InitialSpeaker("s1", "Alice"),),
    segments=(InitialSegment("s1", Decimal(0), Decimal(1), "Alice will send the report"),),
)


@dataclass(frozen=True)
class Team:
    service: MeetingService
    owner: UUID
    member: UUID
    outsider: UUID
    workspace: UUID
    folder: UUID
    meeting: UUID


async def team(session: AsyncSession) -> Team:
    owner, folder = await AsyncDatabase.add_workspace(session)
    workspace = await session.scalar(select(Folder.workspace_id).where(Folder.folder_id == folder))
    assert workspace is not None
    meeting = await AsyncDatabase.add_meeting(session, (owner, folder))
    member = (await AsyncDatabase.add_account(session, uuid4().hex)).user_id
    outsider = (await AsyncDatabase.add_account(session, uuid4().hex)).user_id
    session.add(
        WorkspaceMembership(workspace_id=workspace, user_id=member, role=WorkspaceRole.MEMBER)
    )
    await session.flush()
    return Team(pipeline_service(session), owner, member, outsider, workspace, folder, meeting)


async def shared_with_outsider(session: AsyncSession, unit: Team, *, redact: bool) -> UUID:
    share = ExternalShare(
        share_id=uuid4(),
        meeting_id=unit.meeting,
        created_by_user_id=unit.owner,
        token_hash=uuid4().hex,
        redact_speaker_names=redact,
        created_at=NOW,
        recipient_user_id=unit.outsider,
        revoked_at=None,
    )
    session.add(share)
    await session.flush()
    return share.share_id


async def refusal(call: Awaitable[object]) -> Failure | None:
    try:
        await call
    except UseCaseError as error:
        return error.code
    return None


@pytest.mark.slow
def test_recording_into_an_unknown_folder_is_invalid(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        recording = RecordingInput(
            storage_key=f"meetings/{uuid4()}",
            recorded_at=NOW,
            source=MeetingSource.UPLOAD,
            folder_id=uuid4(),
        )
        return await refusal(unit.service.create(unit.owner, unit.workspace, recording, NOW))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.VALIDATION_ERROR


@pytest.mark.slow
def test_member_cannot_delete_someone_elses_meeting(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        return await refusal(unit.service.delete(unit.member, unit.meeting, NOW))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


@pytest.mark.slow
def test_meeting_deletion_is_audited(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[list[tuple[AuditAction, UUID]], UUID]:
        unit = await team(session)
        await unit.service.delete(unit.owner, unit.meeting, NOW)
        events = await session.execute(
            select(AuditEvent.action, AuditEvent.actor_user_id).where(
                AuditEvent.meeting_id == unit.meeting
            )
        )
        return [(action, actor) for action, actor in events], unit.owner

    # Act
    events, owner = async_database.run(scenario)
    # Assert
    assert events == [(AuditAction.MEETING_DELETED, owner)]


@pytest.mark.slow
def test_update_without_changes_is_invalid(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        return await refusal(unit.service.update(unit.owner, unit.meeting, NOW))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.VALIDATION_ERROR


@pytest.mark.slow
def test_meeting_cannot_move_to_an_unknown_folder(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        return await refusal(unit.service.update(unit.owner, unit.meeting, NOW, folder_id=uuid4()))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.VALIDATION_ERROR


# --- Folders ---


@pytest.mark.slow
def test_member_cannot_create_a_folder(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        return await refusal(unit.service.create_folder(unit.member, unit.workspace, "Sales", NOW))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


@pytest.mark.slow
def test_folder_name_must_be_unique_in_the_workspace(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        await unit.service.create_folder(unit.owner, unit.workspace, "Sales", NOW)
        return await refusal(unit.service.create_folder(unit.owner, unit.workspace, "Sales", NOW))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.FOLDER_EXISTS


@pytest.mark.slow
@pytest.mark.parametrize("name", ["   ", "Sales\nTeam"], ids=["blank", "control-character"])
def test_unprintable_folder_name_is_invalid(async_database: AsyncDatabase, name: str) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        return await refusal(unit.service.create_folder(unit.owner, unit.workspace, name, NOW))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.VALIDATION_ERROR


@pytest.mark.slow
def test_renamed_folder_keeps_the_trimmed_name(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> str:
        unit = await team(session)
        folder = await unit.service.create_folder(unit.owner, unit.workspace, "Sales", NOW)
        renamed = await unit.service.rename_folder(
            unit.owner, unit.workspace, folder.folder_id, "  Marketing  "
        )
        return renamed.name

    # Act
    name = async_database.run(scenario)
    # Assert
    assert name == "Marketing"


@pytest.mark.slow
def test_folder_cannot_be_renamed_to_a_taken_name(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        await unit.service.create_folder(unit.owner, unit.workspace, "Sales", NOW)
        folder = await unit.service.create_folder(unit.owner, unit.workspace, "Marketing", NOW)
        return await refusal(
            unit.service.rename_folder(unit.owner, unit.workspace, folder.folder_id, "Sales")
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.FOLDER_EXISTS


@pytest.mark.slow
def test_folder_count_leaves_out_meetings_the_member_cannot_see(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        unit = await team(session)
        await AsyncDatabase.add_meeting(
            session, (unit.owner, unit.folder), access_mode=AccessMode.RESTRICTED
        )
        return await unit.service.folder_count(unit.member, unit.workspace, unit.folder)

    # Act
    count = async_database.run(scenario)
    # Assert
    assert count == 1


@pytest.mark.slow
def test_folder_counts_are_keyed_by_folder(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        unit = await team(session)
        counts = await unit.service.folder_counts(unit.owner, unit.workspace, [unit.folder])
        return counts == {unit.folder: 1}

    # Act
    counted = async_database.run(scenario)
    # Assert
    assert counted


@pytest.mark.slow
def test_nonmember_cannot_restore_a_folder(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        folders = FolderService(
            FolderRepository(session),
            WorkspaceMembershipService(MembershipRepository(session)),
            AuditWriter(session),
        )
        return await refusal(folders.restore_folder(unit.outsider, unit.workspace, uuid4(), NOW))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.NOT_FOUND


@pytest.mark.slow
def test_member_cannot_restore_a_folder(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        folders = FolderService(
            FolderRepository(session),
            WorkspaceMembershipService(MembershipRepository(session)),
            AuditWriter(session),
        )
        return await refusal(folders.restore_folder(unit.member, unit.workspace, uuid4(), NOW))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


# --- Transcripts ---


@pytest.mark.slow
def test_revisions_list_the_original_and_the_edit(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        unit = await team(session)
        original = await unit.service.save_initial_transcript(unit.meeting, ALICE, NOW)
        await unit.service.edit_transcript(
            unit.owner,
            unit.meeting,
            TranscriptEdit(
                original.revision.revision_id, {original.segments[0].segment_id: "Fixed"}, {}
            ),
            NOW + timedelta(minutes=1),
        )
        return len(await unit.service.revisions(unit.member, unit.meeting))

    # Act
    count = async_database.run(scenario)
    # Assert
    assert count == 2


@pytest.mark.slow
def test_revisions_of_an_untranscribed_meeting_are_refused(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        return await refusal(unit.service.revisions(unit.owner, unit.meeting))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.NOT_TRANSCRIBED


@pytest.mark.slow
def test_edit_of_an_unknown_segment_is_invalid(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        original = await unit.service.save_initial_transcript(unit.meeting, ALICE, NOW)
        edit = TranscriptEdit(original.revision.revision_id, {uuid4(): "Fixed"}, {})
        return await refusal(unit.service.edit_transcript(unit.owner, unit.meeting, edit, NOW))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.VALIDATION_ERROR


@pytest.mark.slow
def test_edit_without_changes_is_invalid(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        original = await unit.service.save_initial_transcript(unit.meeting, ALICE, NOW)
        edit = TranscriptEdit(original.revision.revision_id, {}, {})
        return await refusal(unit.service.edit_transcript(unit.owner, unit.meeting, edit, NOW))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.VALIDATION_ERROR


type EditAudit = tuple[AuditAction, UUID, UUID | None]


@pytest.mark.slow
@pytest.mark.parametrize(
    ("change", "action"),
    [("text", AuditAction.TRANSCRIPT_EDITED), ("speaker", AuditAction.SPEAKER_RENAMED)],
)
def test_transcript_edit_is_audited_by_kind_of_change(
    async_database: AsyncDatabase, change: str, action: AuditAction
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[list[EditAudit], EditAudit]:
        unit = await team(session)
        original = await unit.service.save_initial_transcript(unit.meeting, ALICE, NOW)
        text_changes, speaker_changes = {
            "text": ({original.segments[0].segment_id: "Fixed"}, {}),
            "speaker": ({}, {original.speakers[0].speaker_id: "Bob"}),
        }[change]
        edited = await unit.service.edit_transcript(
            unit.member,
            unit.meeting,
            TranscriptEdit(original.revision.revision_id, text_changes, speaker_changes),
            NOW + timedelta(minutes=1),
        )
        events = await session.execute(
            select(AuditEvent.action, AuditEvent.actor_user_id, AuditEvent.subject_id).where(
                AuditEvent.meeting_id == unit.meeting
            )
        )
        found = [(kind, actor, subject) for kind, actor, subject in events]
        return found, (action, unit.member, edited.revision.revision_id)

    # Act
    events, expected = async_database.run(scenario)
    # Assert
    assert events == [expected]


@pytest.mark.slow
def test_context_holds_other_transcribed_meetings_of_the_folder(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> bool:
        unit = await team(session)
        place = (unit.owner, unit.folder)
        other = await AsyncDatabase.add_meeting(session, place)
        await AsyncDatabase.add_meeting(session, place)
        for transcribed_id in (unit.meeting, other):
            await unit.service.save_initial_transcript(
                transcribed_id, replace(ALICE, job_id=uuid4()), NOW
            )
        found = await unit.service.context(unit.owner, unit.meeting)
        return [version.transcript.meeting_id for version in found] == [other]

    # Act
    matches = async_database.run(scenario)
    # Assert
    assert matches


# --- Shared views ---


@pytest.mark.slow
@pytest.mark.parametrize(
    ("redact", "expected"), [(True, ["Speaker 1"]), (False, ["Alice"])], ids=["redacted", "named"]
)
def test_shared_transcript_names_speakers_as_the_share_says(
    async_database: AsyncDatabase, *, redact: bool, expected: list[str]
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[str]:
        unit = await team(session)
        await unit.service.save_initial_transcript(unit.meeting, ALICE, NOW)
        share_id = await shared_with_outsider(session, unit, redact=redact)
        version = await unit.service.shared_transcript(unit.outsider, share_id, unit.meeting)
        return [speaker.display_name for speaker in version.speakers]

    # Act
    names = async_database.run(scenario)
    # Assert
    assert names == expected


@pytest.mark.slow
@pytest.mark.parametrize("surface", ["transcript", "notes"])
def test_share_does_not_open_another_meeting(async_database: AsyncDatabase, surface: str) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        other = await AsyncDatabase.add_meeting(session, (unit.owner, unit.folder))
        share_id = await shared_with_outsider(session, unit, redact=False)
        if surface == "transcript":
            return await refusal(unit.service.shared_transcript(unit.outsider, share_id, other))
        return await refusal(unit.service.shared_notes(unit.outsider, share_id, other))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.NOT_FOUND


@pytest.mark.slow
def test_unredacted_shared_notes_keep_the_names(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[str]:
        unit = await team(session)
        session.add(
            Note(
                note_id=uuid4(),
                meeting_id=unit.meeting,
                template=NotesTemplate.SUMMARY,
                content="Alice will send the report",
                model_name="test",
                provider=LlmProvider.WHADIO,
                created_at=NOW,
                created_by_user_id=None,
            )
        )
        await session.flush()
        share_id = await shared_with_outsider(session, unit, redact=False)
        versions = await unit.service.shared_notes(unit.outsider, share_id, unit.meeting)
        return [version.note.content for version in versions]

    # Act
    contents = async_database.run(scenario)
    # Assert
    assert contents == ["Alice will send the report"]


# --- Glossary ---


@pytest.mark.slow
def test_added_term_is_listed_in_the_glossary(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[str]:
        unit = await team(session)
        await unit.service.add_term(
            unit.member,
            GlossaryTerm(
                workspace_id=unit.workspace,
                term="  Whadio ",
                preferred_form="Whadio",
                description="",
                source_meeting_id=unit.meeting,
            ),
        )
        return [item.term for item in await unit.service.glossary(unit.owner, unit.workspace)]

    # Act
    terms = async_database.run(scenario)
    # Assert
    assert terms == ["Whadio"]


@pytest.mark.slow
def test_term_is_unique_whatever_its_case(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        await unit.service.add_term(
            unit.owner,
            GlossaryTerm(
                workspace_id=unit.workspace, term="Whadio", preferred_form="Whadio", description=""
            ),
        )
        return await refusal(
            unit.service.add_term(
                unit.owner,
                GlossaryTerm(
                    workspace_id=unit.workspace,
                    term="WHADIO",
                    preferred_form="Whadio",
                    description="",
                ),
            )
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.TERM_EXISTS


@pytest.mark.slow
def test_term_cannot_cite_a_meeting_of_another_workspace(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        _, other_folder = await AsyncDatabase.add_workspace(session)
        other_workspace = await session.scalar(
            select(Folder.workspace_id).where(Folder.folder_id == other_folder)
        )
        assert other_workspace is not None
        session.add(
            WorkspaceMembership(
                workspace_id=other_workspace, user_id=unit.owner, role=WorkspaceRole.MEMBER
            )
        )
        await session.flush()
        return await refusal(
            unit.service.add_term(
                unit.owner,
                GlossaryTerm(
                    workspace_id=other_workspace,
                    term="Whadio",
                    preferred_form="Whadio",
                    description="",
                    source_meeting_id=unit.meeting,
                ),
            )
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.NOT_FOUND


@pytest.mark.slow
@pytest.mark.parametrize("change", ["delete", "update"])
def test_member_cannot_change_someone_elses_term(
    async_database: AsyncDatabase, change: str
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        term = await unit.service.add_term(
            unit.owner,
            GlossaryTerm(
                workspace_id=unit.workspace, term="Whadio", preferred_form="Whadio", description=""
            ),
        )
        if change == "delete":
            return await refusal(
                unit.service.delete_term(unit.member, unit.workspace, term.term_id)
            )
        return await refusal(
            unit.service.update_term(
                unit.member, unit.workspace, term.term_id, TermUpdate(description="mine")
            )
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


@pytest.mark.slow
def test_member_may_delete_their_own_term(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> list[GlossaryTerm]:
        unit = await team(session)
        term = await unit.service.add_term(
            unit.member,
            GlossaryTerm(
                workspace_id=unit.workspace, term="Whadio", preferred_form="Whadio", description=""
            ),
        )
        await unit.service.delete_term(unit.member, unit.workspace, term.term_id)
        return await unit.service.glossary(unit.member, unit.workspace)

    # Act
    terms = async_database.run(scenario)
    # Assert
    assert terms == []


@pytest.mark.slow
def test_term_cannot_be_renamed_to_another_terms_spelling(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await team(session)
        await unit.service.add_term(
            unit.owner,
            GlossaryTerm(
                workspace_id=unit.workspace, term="Whadio", preferred_form="Whadio", description=""
            ),
        )
        other = await unit.service.add_term(
            unit.owner,
            GlossaryTerm(
                workspace_id=unit.workspace, term="Meet", preferred_form="Meet", description=""
            ),
        )
        return await refusal(
            unit.service.update_term(
                unit.owner, unit.workspace, other.term_id, TermUpdate(term="whadio")
            )
        )

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.TERM_EXISTS


@pytest.mark.slow
def test_term_update_changes_only_the_given_fields(async_database: AsyncDatabase) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[str, str, str]:
        unit = await team(session)
        term = await unit.service.add_term(
            unit.owner,
            GlossaryTerm(
                workspace_id=unit.workspace, term="Whadio", preferred_form="Whadio", description=""
            ),
        )
        updated = await unit.service.update_term(
            unit.owner,
            unit.workspace,
            term.term_id,
            TermUpdate(preferred_form=" WhAdio ", description="The product"),
        )
        return updated.term, updated.preferred_form, updated.description

    # Act
    fields = async_database.run(scenario)
    # Assert
    assert fields == ("Whadio", "WhAdio", "The product")
