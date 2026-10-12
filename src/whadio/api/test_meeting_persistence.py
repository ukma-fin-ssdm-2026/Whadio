import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from ..accounts.enums import LlmProvider, NotesTemplate
from ..accounts.repositories import MembershipRepository
from ..accounts.services import WorkspaceMembershipService
from ..audit.services import AuditWriter
from ..meetings.contracts import InitialSegment, InitialSpeaker, InitialTranscript, ProcessingUpdate
from ..meetings.enums import (
    AccessMode,
    MeetingSource,
    ProcessingFailure,
    ProcessingState,
    RecordingStatus,
)
from ..meetings.models import Meeting, Note, Transcript
from ..meetings.repositories import FolderRepository
from ..meetings.retention import IRetentionMeetings, RetentionMeetings
from ..meetings.services import FolderService, RecordingInput, TranscriptEdit
from ..retention.services import RetentionService, StorageUnavailableError
from ..shared.database import DatabaseSettings
from ..shared.errors import Failure, UseCaseError
from ..shared.pagination import ListCursor, ListWindow
from .access_policy.routes import ShareRead
from .core.schemas import Page
from .meetings.routes_content import FolderRead
from .meetings.views import meeting_read
from .test_composition import RetentionNotices, client_fixture, unit_fixture

pytestmark = pytest.mark.slow


def test_older_notes_page_has_no_current_version(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            for age in range(3):
                unit.session.add(
                    Note(
                        meeting_id=unit.meeting,
                        template=NotesTemplate.SUMMARY,
                        provider=LlmProvider.WHADIO,
                        model_name="test",
                        content="test",
                        created_at=now - timedelta(minutes=age),
                    )
                )
            await unit.session.flush()
            first = await unit.meetings.notes(unit.owner, unit.meeting, ListWindow(1))
            anchor = first[0].note
            # Act
            older = await unit.meetings.notes(
                unit.owner,
                unit.meeting,
                ListWindow(1, ListCursor(anchor.created_at.isoformat(), anchor.note_id)),
            )
            # Assert
            assert (len(older), older[0].is_current) == (1, False)

    asyncio.run(scenario())


def initial_transcript() -> InitialTranscript:
    return InitialTranscript(
        uuid4(),
        "en",
        "test",
        (InitialSpeaker("speaker", "Ann"),),
        (InitialSegment("speaker", Decimal(0), Decimal(1), "original text"),),
    )


def test_initial_transcript_replay_preserves_edits(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            meeting = await unit.meetings.create(
                unit.owner,
                unit.workspace,
                recording_input(),
                datetime.now(UTC),
            )
            result = initial_transcript()
            original = await unit.meetings.save_initial_transcript(
                meeting.meeting_id, result, datetime.now(UTC)
            )
            edited = await unit.meetings.edit_transcript(
                unit.owner,
                meeting.meeting_id,
                TranscriptEdit(
                    original.revision.revision_id, {original.segments[0].segment_id: "edited"}, {}
                ),
                datetime.now(UTC),
            )
            # Act
            replay = await unit.meetings.save_initial_transcript(
                meeting.meeting_id, result, datetime.now(UTC)
            )
            source = await unit.meetings.transcript(
                unit.owner, meeting.meeting_id, original.original_revision_id
            )
            # Assert
            assert (replay.revision.revision_id, source.segments[0].text) == (
                edited.revision.revision_id,
                "original text",
            )

    asyncio.run(scenario())


def recording_input() -> RecordingInput:
    return RecordingInput("new-recording", datetime.now(UTC), MeetingSource.UPLOAD)


def test_initial_transcript_rejects_unknown_speaker_atomically(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            meeting = await unit.meetings.create(
                unit.owner, unit.workspace, recording_input(), datetime.now(UTC)
            )
            invalid = InitialTranscript(
                uuid4(),
                "en",
                "test",
                (),
                (InitialSegment("missing", Decimal(0), Decimal(1), "text"),),
            )
            # Act
            with pytest.raises(UseCaseError) as error:
                await unit.meetings.save_initial_transcript(
                    meeting.meeting_id, invalid, datetime.now(UTC)
                )
            stored = await unit.session.scalar(
                select(Transcript).where(Transcript.meeting_id == meeting.meeting_id)
            )
            # Assert
            assert (error.value.code, stored) == (Failure.VALIDATION_ERROR, None)

    asyncio.run(scenario())


def test_processing_failure_is_visible_and_cleared_on_retry(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            # Act
            await unit.meetings.save_processing_state(
                unit.meeting,
                ProcessingUpdate(
                    ProcessingState.FAILED,
                    ProcessingFailure.PROVIDER_UNAVAILABLE,
                ),
            )
            failed = meeting_read(
                await unit.meetings.get(unit.owner, unit.meeting), unit.workspace, is_edited=False
            )
            await unit.meetings.save_processing_state(
                unit.meeting, ProcessingUpdate(ProcessingState.QUEUED)
            )
            retried = await unit.meetings.get(unit.owner, unit.meeting)
            # Assert
            assert (failed.failure_reason, retried.failure_reason) == ("provider_unavailable", None)

    asyncio.run(scenario())


def test_recipient_share_list_excludes_other_accounts_and_revocations(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            shares = [
                await unit.access.create_share(unit.owner, unit.meeting, now, redact=False)
                for _ in range(3)
            ]
            for share in shares[:2]:
                request = await unit.access.request_access(
                    unit.outsider, share.share.share_id, share.token, now
                )
                await unit.access.decide(
                    unit.owner, request.share_access_request_id, now, approve=True
                )
            await unit.access.revoke(unit.owner, shares[1].share.share_id, now)
            # Act
            async with client_fixture(unit, unit.outsider) as client:
                response = await client.get("/api/v1/users/me/shares")
            # Assert
            assert [
                row.id for row in Page[ShareRead].model_validate_json(response.content).items
            ] == [shares[0].share.share_id]

    asyncio.run(scenario())


def test_folder_restore_preserves_content_and_restricted_access(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            folder_id = (await unit.meetings.get(unit.owner, unit.meeting)).folder_id
            service = FolderService(
                FolderRepository(unit.session),
                WorkspaceMembershipService(MembershipRepository(unit.session)),
                AuditWriter(unit.session),
            )
            await unit.access.replace_access(
                unit.owner, unit.meeting, {unit.owner}, datetime.now(UTC), restricted=True
            )
            before = await unit.meetings.transcript(unit.owner, unit.meeting)
            # Act
            await service.delete_folder(unit.owner, unit.workspace, folder_id, datetime.now(UTC))
            await service.restore_folder(unit.owner, unit.workspace, folder_id, datetime.now(UTC))
            meeting = await unit.meetings.get(unit.owner, unit.meeting)
            after = await unit.meetings.transcript(unit.owner, unit.meeting)
            notes = await unit.meetings.notes(unit.owner, unit.meeting)
            # Assert
            assert (
                meeting.folder_id,
                meeting.storage_path,
                meeting.access_mode,
                after.revision.revision_id,
                notes[0].note.content,
            ) == (
                folder_id,
                "recording/test",
                AccessMode.RESTRICTED,
                before.revision.revision_id,
                "Alice will send the report",
            )

    asyncio.run(scenario())


def test_folder_restore_refuses_to_overwrite_a_later_move(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            original = (await unit.meetings.get(unit.owner, unit.meeting)).folder_id
            service = FolderService(
                FolderRepository(unit.session),
                WorkspaceMembershipService(MembershipRepository(unit.session)),
                AuditWriter(unit.session),
            )
            await service.delete_folder(unit.owner, unit.workspace, original, datetime.now(UTC))
            other = await unit.meetings.create_folder(
                unit.owner, unit.workspace, "other", datetime.now(UTC)
            )
            await unit.meetings.update(
                unit.owner, unit.meeting, datetime.now(UTC), folder_id=other.folder_id
            )
            # Act
            with pytest.raises(UseCaseError) as error:
                await service.restore_folder(
                    unit.owner, unit.workspace, original, datetime.now(UTC)
                )
            # Assert
            assert error.value.code == Failure.FOLDER_RECOVERY_CONFLICT

    asyncio.run(scenario())


def test_redacted_notes_preserve_words_containing_a_speaker_name(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            current = await unit.meetings.transcript(unit.owner, unit.meeting)
            await unit.meetings.edit_transcript(
                unit.owner,
                unit.meeting,
                TranscriptEdit(
                    current.revision.revision_id, {}, {current.speakers[0].speaker_id: "Ann"}
                ),
                datetime.now(UTC),
            )
            unit.session.add(
                Note(
                    meeting_id=unit.meeting,
                    template=NotesTemplate.SUMMARY,
                    provider=LlmProvider.WHADIO,
                    model_name="test",
                    content="Ann: Annual report",
                    created_at=datetime.now(UTC),
                )
            )
            await unit.session.flush()
            share = await unit.access.create_share(
                unit.owner, unit.meeting, datetime.now(UTC), redact=True
            )
            request = await unit.access.request_access(
                unit.outsider, share.share.share_id, share.token, datetime.now(UTC)
            )
            await unit.access.decide(
                unit.owner, request.share_access_request_id, datetime.now(UTC), approve=True
            )
            # Act
            notes = await unit.meetings.shared_notes(
                unit.outsider, share.share.share_id, unit.meeting
            )
            # Assert
            assert notes[0].note.content == "Speaker 1: Annual report"

    asyncio.run(scenario())


def test_folder_cursor_survives_deletion_of_its_anchor(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            await unit.meetings.create_folder(unit.owner, unit.workspace, "aaa", datetime.now(UTC))
            service = FolderService(
                FolderRepository(unit.session),
                WorkspaceMembershipService(MembershipRepository(unit.session)),
                AuditWriter(unit.session),
            )
            async with client_fixture(unit, unit.owner) as client:
                response = await client.get(f"/api/v1/workspaces/{unit.workspace}/folders?limit=2")
                first = Page[FolderRead].model_validate_json(response.content)
            anchor = first.items[-1].id
            await service.delete_folder(unit.owner, unit.workspace, anchor, datetime.now(UTC))
            # Act
            async with client_fixture(unit, unit.owner) as client:
                second = await client.get(
                    f"/api/v1/workspaces/{unit.workspace}/folders",
                    params={
                        "limit": 2,
                        "cursor": first.pagination.next_cursor,
                    },
                )
            # Assert
            assert [
                row.name for row in Page[FolderRead].model_validate_json(second.content).items
            ] == ["test"]

    asyncio.run(scenario())


def test_retention_processes_later_batches_when_first_batch_fails(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            good = await unit.meetings.get(unit.owner, unit.meeting)
            good.recording_delete_after = now - timedelta(days=1)
            for index in range(100):
                unit.session.add(
                    Meeting(
                        meeting_id=UUID(int=index + 1),
                        folder_id=good.folder_id,
                        created_by_user_id=unit.owner,
                        name="test",
                        name_is_generated=False,
                        source_type=MeetingSource.UPLOAD,
                        recording_status=RecordingStatus.COMPLETE,
                        processing_state=ProcessingState.PROCESSED,
                        storage_path="bad",
                        recorded_at=now - timedelta(days=91),
                        recording_delete_after=now - timedelta(days=1),
                        access_mode=AccessMode.WORKSPACE,
                    )
                )
            await unit.session.flush()

            class Transactions:
                @asynccontextmanager
                async def transaction(self) -> AsyncGenerator[IRetentionMeetings]:
                    async with unit.session.begin_nested():
                        yield RetentionMeetings(
                            unit.session, unit.access.policy, RetentionNotices()
                        )

            class Storage:
                async def delete(self, key: str) -> None:
                    if key == "bad":
                        raise StorageUnavailableError

            # Act
            result = await RetentionService(Transactions(), Storage()).run(now)
            # Assert
            assert (len(result.failed), result.deleted) == (100, [unit.meeting])

    asyncio.run(scenario())
