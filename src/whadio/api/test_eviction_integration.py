import asyncio
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..accounts.enums import LlmProvider, NotesTemplate
from ..accounts.repositories import MembershipRepository
from ..audit.models import AuditEvent
from ..meetings.contracts import EvictionNotice
from ..meetings.enums import MeetingSource, RecordingStatus
from ..meetings.models import Meeting, Note, RecordingDeletion
from ..meetings.persistence import (
    AssembledRecording,
    GeneratedNotes,
    MeetingPersistence,
    PersistenceDependencies,
)
from ..meetings.processing import IMeetingProcessing
from ..meetings.repositories import MeetingRepository
from ..meetings.services import RecordingInput
from ..notifications.repositories import notice_payload
from ..notifications.templates import HostedEviction, Notice, NoticeKind
from ..shared.database import DatabaseSettings
from ..shared.errors import Failure, UseCaseError
from .app import create_app
from .composition import (
    OutboxEvictionNotices,
    Processing,
    RuntimeIntegrations,
    Session,
    UnavailableMeetingProcessing,
    eviction_notifications,
    transaction,
)
from .test_composition import (
    EvictionNotices,
    FailingContentAuditWriter,
    persistence_fixture,
    reserved_notices,
    unit_fixture,
)

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("share_state", ["absent", "active", "revoked"])
def test_eviction_title_permission_for_uploader_outside_old_workspace(
    database_settings: DatabaseSettings, share_state: str
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            if share_state != "absent":
                share = await unit.access.create_share(unit.owner, unit.meeting, now, redact=False)
                request = await unit.access.request_access(
                    unit.outsider, share.share.share_id, share.token, now
                )
                await unit.access.decide(
                    unit.owner, request.share_access_request_id, now, approve=True
                )
                if share_state == "revoked":
                    await unit.access.revoke(unit.owner, share.share.share_id, now)
            scope = await MeetingRepository(unit.session).scope(unit.meeting)
            # Act
            recipients = await unit.access.policy.eviction_recipients(scope, unit.outsider)
            # Assert
            assert recipients == {unit.owner: True, unit.outsider: share_state == "active"}

    asyncio.run(scenario())


def test_runtime_processing_factory_shares_use_case_session_and_rolls_back_on_failure(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            sessions: list[AsyncSession] = []

            def processing_factory(session: AsyncSession) -> IMeetingProcessing:
                sessions.append(session)
                return UnavailableMeetingProcessing()

            app = create_app(
                unit.database,
                integrations=RuntimeIntegrations(processing_factory),
            )

            async def session_dependency() -> AsyncGenerator[AsyncSession]:
                async with unit.session.begin_nested():
                    yield unit.session

            app.dependency_overrides[transaction] = session_dependency

            @app.post("/integration-probe")
            async def probe(
                session: Session,
                processing: Processing,
            ) -> None:
                session.add(RecordingDeletion(storage_key="integration-probe"))
                await session.flush()
                await processing.queue_transcription(unit.meeting)

            # Act
            async with AsyncClient(
                transport=ASGITransport(app), base_url="https://example.test"
            ) as client:
                response = await client.post("/integration-probe")
            pending = await unit.session.scalar(select(RecordingDeletion.deletion_id))
            # Assert
            assert (response.status_code, sessions, pending) == (
                503,
                [unit.session],
                None,
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("selected", ["both", "creator", "uploader"])
def test_eviction_captures_required_recipients_and_authorized_names(
    database_settings: DatabaseSettings, selected: str
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            readers = {
                "both": {unit.owner, unit.member},
                "creator": {unit.owner},
                "uploader": {unit.member},
            }[selected]
            old = await unit.meetings.get(unit.owner, unit.meeting)
            name = old.name
            await unit.access.replace_access(
                unit.owner, unit.meeting, readers, now, restricted=True
            )
            notices = EvictionNotices()
            # Act
            created = await persistence_fixture(unit, hosted_limit=1, notifications=notices).ingest(
                unit.member,
                unit.workspace,
                RecordingInput("recording/new", now, MeetingSource.UPLOAD),
                now,
            )
            event = await unit.session.scalar(
                select(AuditEvent)
                .where(AuditEvent.meeting_id == unit.meeting)
                .where(AuditEvent.action == "meeting_evicted")
            )
            # Assert
            assert (
                {n.recipient_id: n.meeting_name for n in notices.notices},
                {(n.meeting_id, n.triggering_meeting_id) for n in notices.notices},
                None if event is None else (event.actor_user_id, event.details),
            ) == (
                {
                    recipient: name if recipient in readers else None
                    for recipient in (unit.owner, unit.member)
                },
                {(unit.meeting, created.meeting_id)},
                (unit.member, {"meeting_id": str(created.meeting_id)}),
            )

    asyncio.run(scenario())


def test_eviction_notifies_same_uploader_and_creator_once(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            notices = EvictionNotices()
            # Act
            await persistence_fixture(unit, hosted_limit=1, notifications=notices).ingest(
                unit.owner,
                unit.workspace,
                RecordingInput("recording/new", now, MeetingSource.UPLOAD),
                now,
            )
            # Assert
            assert [n.recipient_id for n in notices.notices] == [unit.owner]

    asyncio.run(scenario())


def test_eviction_does_not_notify_departed_creator(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            old = await unit.meetings.get(unit.owner, unit.meeting)
            old.created_by_user_id = unit.outsider
            await unit.session.flush()
            now = datetime.now(UTC)
            notices = EvictionNotices()
            # Act
            await persistence_fixture(unit, hosted_limit=1, notifications=notices).ingest(
                unit.member,
                unit.workspace,
                RecordingInput("recording/new", now, MeetingSource.UPLOAD),
                now,
            )
            # Assert
            assert [n.recipient_id for n in notices.notices] == [unit.member]

    asyncio.run(scenario())


def test_capture_started_at_capacity_evicts_nothing(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            # Act
            await persistence_fixture(unit, hosted_limit=1).ingest(
                unit.member,
                unit.workspace,
                RecordingInput(None, now, MeetingSource.EXTENSION, consent_confirmed_at=now),
                now,
            )
            kept = await unit.session.get(Meeting, unit.meeting)
            # Assert
            assert kept is not None

    asyncio.run(scenario())


def test_assembled_capture_at_capacity_evicts_the_earliest_meeting(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            persistence = persistence_fixture(unit, hosted_limit=1)
            captured = await persistence.ingest(
                unit.member,
                unit.workspace,
                RecordingInput(None, now, MeetingSource.EXTENSION, consent_confirmed_at=now),
                now,
            )
            # Act
            await persistence.attach_recording(
                unit.member,
                captured.meeting_id,
                AssembledRecording("recording/captured", RecordingStatus.COMPLETE, ()),
                now,
            )
            event = await unit.session.scalar(
                select(AuditEvent)
                .where(AuditEvent.meeting_id == unit.meeting)
                .where(AuditEvent.action == "meeting_evicted")
            )
            # Assert
            assert (None if event is None else (event.actor_user_id, event.details)) == (
                unit.member,
                {"meeting_id": str(captured.meeting_id)},
            )

    asyncio.run(scenario())


def test_recording_is_not_attached_for_an_account_outside_the_workspace(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            persistence = persistence_fixture(unit)
            captured = await persistence.ingest(
                unit.member,
                unit.workspace,
                RecordingInput(None, now, MeetingSource.EXTENSION, consent_confirmed_at=now),
                now,
            )
            # Act
            with pytest.raises(UseCaseError) as error:
                await persistence.attach_recording(
                    unit.outsider,
                    captured.meeting_id,
                    AssembledRecording("recording/captured", RecordingStatus.COMPLETE, ()),
                    now,
                )
            # Assert
            assert error.value.code == Failure.NOT_FOUND

    asyncio.run(scenario())


class UnavailableOutbox:
    async def reserve(self, recipient_id: UUID, dedupe_key: str, notice: Notice) -> None:
        del recipient_id, dedupe_key, notice
        raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)


def test_eviction_reserves_a_notice_for_each_recipient(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            await unit.access.replace_access(
                unit.owner, unit.meeting, {unit.owner}, now, restricted=True
            )
            # Act
            await persistence_fixture(
                unit, hosted_limit=1, notifications=eviction_notifications(unit.session)
            ).ingest(
                unit.member,
                unit.workspace,
                RecordingInput("recording/new", now, MeetingSource.UPLOAD),
                now,
            )
            reserved = await reserved_notices(unit, unit.owner, unit.member)
            # Assert
            assert sorted(reserved) == sorted(
                (
                    recipient,
                    f"hosted_eviction:{unit.meeting}:{recipient}",
                    NoticeKind.HOSTED_EVICTION,
                    notice_payload(HostedEviction(meeting_name=name)),
                )
                for recipient, name in ((unit.owner, "test"), (unit.member, None))
            )

    asyncio.run(scenario())


def test_repeated_eviction_notice_is_reserved_once(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            notices = eviction_notifications(unit.session)
            notice = EvictionNotice(unit.meeting, uuid4(), unit.owner, "test", now)
            await notices.enqueue(notice)
            # Act
            await notices.enqueue(replace(notice, triggering_meeting_id=uuid4()))
            reserved = await reserved_notices(unit, unit.owner)
            # Assert
            assert len(reserved) == 1

    asyncio.run(scenario())


def test_failed_eviction_reservation_aborts_ingest(database_settings: DatabaseSettings) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            persistence = persistence_fixture(
                unit, hosted_limit=1, notifications=OutboxEvictionNotices(UnavailableOutbox())
            )

            # Act
            async def ingest() -> None:
                async with unit.session.begin_nested():
                    await persistence.ingest(
                        unit.member,
                        unit.workspace,
                        RecordingInput("recording/new", now, MeetingSource.UPLOAD),
                        now,
                    )

            with pytest.raises(UseCaseError):
                await ingest()
            meetings = list(await unit.session.scalars(select(Meeting.meeting_id)))
            events = list(await unit.session.scalars(select(AuditEvent.action)))
            cleanup = list(await unit.session.scalars(select(RecordingDeletion.deletion_id)))
            # Assert
            assert (meetings, events, cleanup) == ([unit.meeting], [], [])

    asyncio.run(scenario())


def test_failed_ingest_rolls_back_notifications_eviction_audit_and_new_meeting(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            now = datetime.now(UTC)
            persistence = persistence_fixture(
                unit, hosted_limit=1, notifications=eviction_notifications(unit.session)
            )

            # Act
            async def ingest() -> None:
                async with unit.session.begin_nested():
                    await persistence.ingest(
                        unit.member,
                        unit.workspace,
                        RecordingInput("recording/new", now, MeetingSource.UPLOAD),
                        now,
                    )
                    await UnavailableMeetingProcessing().queue_transcription(unit.meeting)

            with pytest.raises(UseCaseError):
                await ingest()
            meetings = list(await unit.session.scalars(select(Meeting.meeting_id)))
            notices = await reserved_notices(unit, unit.owner, unit.member)
            events = list(await unit.session.scalars(select(AuditEvent.action)))
            cleanup = list(await unit.session.scalars(select(RecordingDeletion.deletion_id)))
            # Assert
            assert (meetings, notices, events, cleanup) == ([unit.meeting], [], [], [])

    asyncio.run(scenario())


@pytest.mark.parametrize("preset", list(NotesTemplate))
def test_regeneration_audit_records_actual_preset(
    database_settings: DatabaseSettings, preset: NotesTemplate
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            # Act
            await persistence_fixture(unit).save_generated_notes(
                unit.meeting,
                GeneratedNotes(preset, LlmProvider.WHADIO, "test", "notes", "name", ()),
                unit.member,
                datetime.now(UTC),
            )
            event = await unit.session.scalar(
                select(AuditEvent).where(AuditEvent.action == "notes_regenerated")
            )
            # Assert
            assert (None if event is None else event.details) == {"preset": preset.value}

    asyncio.run(scenario())


def test_regeneration_audit_failure_rolls_back_notes_and_generated_name(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> None:
        async with unit_fixture(database_settings) as unit:
            meeting = await unit.meetings.get(unit.owner, unit.meeting)
            meeting.name_is_generated = True
            await unit.session.flush()
            name = meeting.name
            service = MeetingPersistence(
                PersistenceDependencies(
                    unit.meetings,
                    MeetingRepository(unit.session),
                    MembershipRepository(unit.session),
                    FailingContentAuditWriter(),
                    unit.access.policy,
                    EvictionNotices(),
                )
            )
            # Act
            with pytest.raises(UseCaseError):
                async with unit.session.begin_nested():
                    await service.save_generated_notes(
                        unit.meeting,
                        GeneratedNotes(
                            NotesTemplate.INTERVIEW, LlmProvider.WHADIO, "test", "new", "new", ()
                        ),
                        unit.member,
                        datetime.now(UTC),
                    )
            stored = await unit.meetings.get(unit.owner, unit.meeting)
            notes = list(await unit.session.scalars(select(Note.content)))
            events = list(await unit.session.scalars(select(AuditEvent.action)))
            # Assert
            assert (stored.name, notes, events) == (name, ["Alice will send the report"], [])

    asyncio.run(scenario())
