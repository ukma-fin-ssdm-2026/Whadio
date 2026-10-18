import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Select, false, select

from ..access_policy.contracts import MeetingScope
from ..access_policy.models import MeetingAccessGrant
from ..access_policy.services import ContentPath, Permission
from ..accounts.enums import WorkspaceRole
from ..audit.contracts import ContentEvent
from ..audit.enums import AuditAction
from ..shared.errors import Failure, UseCaseError
from ..shared.pagination import ListWindow
from .contracts import ContextReference, MeetingFilter, NoteVersion, TranscriptVersion
from .enums import MeetingSource
from .models import Folder, GlossaryTerm, Meeting, Note, TranscriptRevision
from .services import MeetingService, RecordingInput

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
NAMES_THE_API_ACCEPTS = pytest.mark.parametrize(
    "name", ["0\xad", "0\U0001239a"], ids=["soft-hyphen", "unassigned"]
)
NAMES_THE_API_REFUSES = pytest.mark.parametrize(
    "name", ["0\x1f", "\x1cDesign"], ids=["unit-separator", "file-separator"]
)


class FakeMeetingRepository:
    def __init__(self) -> None:
        self.meeting_rows: dict[UUID, Meeting] = {}
        self.folder_rows: dict[UUID, Folder] = {}
        self.term_rows: dict[UUID, GlossaryTerm] = {}
        self.removed: list[UUID] = []

    async def scope(self, meeting_id: UUID, *, lock: bool = False) -> MeetingScope:
        del lock
        meeting = self.meeting_rows.get(meeting_id)
        if meeting is None:
            raise UseCaseError(Failure.NOT_FOUND)
        workspace_id = self.folder_rows[meeting.folder_id].workspace_id
        restricted = meeting.access_mode == "restricted"
        return MeetingScope(meeting_id, workspace_id, meeting.created_by_user_id, restricted)

    async def get(self, meeting_id: UUID, *, lock: bool = False) -> Meeting:
        del lock
        return self.meeting_rows[meeting_id]

    async def save(self, meeting: Meeting) -> None:
        self.meeting_rows[meeting.meeting_id] = meeting

    async def remove(self, meeting_id: UUID, now: datetime) -> None:
        del now
        self.removed.append(meeting_id)

    async def folders(self, workspace_id: UUID, page: ListWindow | None = None) -> list[Folder]:
        found = [
            folder for folder in self.folder_rows.values() if folder.workspace_id == workspace_id
        ]
        return found if page is None else found[: page.limit]

    async def folder(self, workspace_id: UUID, folder_id: UUID, *, lock: bool = False) -> Folder:
        del lock
        folder = self.folder_rows.get(folder_id)
        if folder is None or folder.workspace_id != workspace_id:
            raise UseCaseError(Failure.NOT_FOUND)
        return folder

    async def folder_name_exists(self, workspace_id: UUID, name: str, exclude: UUID) -> bool:
        return any(
            folder.workspace_id == workspace_id
            and folder.name == name
            and folder.folder_id != exclude
            for folder in self.folder_rows.values()
        )

    async def save_folder(self, folder: Folder) -> None:
        self.folder_rows[folder.folder_id] = folder

    async def glossary(
        self, workspace_id: UUID, page: ListWindow | None = None
    ) -> list[GlossaryTerm]:
        found = [term for term in self.term_rows.values() if term.workspace_id == workspace_id]
        return found if page is None else found[: page.limit]

    async def term(self, workspace_id: UUID, term_id: UUID) -> GlossaryTerm:
        term = self.term_rows.get(term_id)
        if term is None or term.workspace_id != workspace_id:
            raise UseCaseError(Failure.NOT_FOUND)
        return term

    async def save_term(self, term: GlossaryTerm) -> None:
        self.term_rows[term.term_id] = term

    async def remove_term(self, term_id: UUID) -> None:
        del self.term_rows[term_id]

    # --- Not used by the use cases under test ---

    async def capacity_overflow(self, workspace_ids: list[UUID], limit: int) -> list[Meeting]:
        raise NotImplementedError(workspace_ids, limit)

    async def save_notes(self, note: Note, context: tuple[ContextReference, ...]) -> None:
        raise NotImplementedError(note, context)

    async def reserve_upload(self, key: str) -> None:
        raise NotImplementedError(key)

    async def lock_upload(self, key: str) -> None:
        raise NotImplementedError(key)

    async def release_upload(self, key: str) -> None:
        raise NotImplementedError(key)

    async def save_initial(self, version: TranscriptVersion) -> None:
        raise NotImplementedError(version)

    async def folder_counts(
        self, workspace_id: UUID, folder_ids: list[UUID], grants: Select[UUID]
    ) -> dict[UUID, int]:
        raise NotImplementedError(workspace_id, folder_ids, grants)

    async def visible(self, filters: MeetingFilter, grants: Select[UUID]) -> list[Meeting]:
        raise NotImplementedError(filters, grants)

    async def version(self, meeting_id: UUID, revision_id: UUID | None = None) -> TranscriptVersion:
        raise NotImplementedError(meeting_id, revision_id)

    async def revisions(
        self, meeting_id: UUID, page: ListWindow | None = None
    ) -> list[TranscriptRevision]:
        raise NotImplementedError(meeting_id, page)

    async def save_version(self, version: TranscriptVersion) -> None:
        raise NotImplementedError(version)

    async def notes(self, meeting_id: UUID, page: ListWindow | None = None) -> list[NoteVersion]:
        raise NotImplementedError(meeting_id, page)

    async def processed_in_folder(self, folder_id: UUID, limit: int) -> list[Meeting]:
        raise NotImplementedError(folder_id, limit)

    async def workspace_meetings(self, workspace_id: UUID) -> list[UUID]:
        raise NotImplementedError(workspace_id)


class FakePolicy:
    def __init__(self) -> None:
        self.roles: dict[tuple[UUID, UUID], WorkspaceRole] = {}

    def granted_meetings(self, user_id: UUID) -> Select[UUID]:
        return select(MeetingAccessGrant.meeting_id).where(
            MeetingAccessGrant.user_id == user_id, false()
        )

    async def workspace_role(self, workspace_id: UUID, user_id: UUID) -> WorkspaceRole:
        role = self.roles.get((workspace_id, user_id))
        if role is None:
            raise UseCaseError(Failure.NOT_FOUND)
        return role

    async def authorize(self, scope: MeetingScope, user_id: UUID) -> Permission:
        return Permission(
            await self.workspace_role(scope.workspace_id, user_id), meeting_id=scope.meeting_id
        )

    async def authorize_share(self, share_id: UUID, user_id: UUID, path: ContentPath) -> Permission:
        raise NotImplementedError(share_id, user_id, path)


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[ContentEvent] = []

    async def write(self, event: ContentEvent) -> None:
        self.events.append(event)


@dataclass(frozen=True)
class Team:
    meetings: MeetingService
    repository: FakeMeetingRepository
    audit: FakeAudit
    owner: UUID
    member: UUID
    workspace: UUID
    default_folder: UUID
    meeting: UUID


def team() -> Team:
    owner, member, workspace = uuid4(), uuid4(), uuid4()
    repository, policy, audit = FakeMeetingRepository(), FakePolicy(), FakeAudit()
    policy.roles[workspace, owner] = WorkspaceRole.OWNER
    policy.roles[workspace, member] = WorkspaceRole.MEMBER
    folder = Folder(
        folder_id=uuid4(), workspace_id=workspace, name="default", created_at=NOW, is_default=True
    )
    repository.folder_rows[folder.folder_id] = folder
    meetings = MeetingService(repository, policy, audit)
    meeting = asyncio.run(meetings.create(owner, workspace, recording(), NOW))
    audit.events.clear()
    return Team(
        meetings, repository, audit, owner, member, workspace, folder.folder_id, meeting.meeting_id
    )


def recording(
    source: MeetingSource = MeetingSource.UPLOAD,
    folder_id: UUID | None = None,
    consent_confirmed_at: datetime | None = None,
) -> RecordingInput:
    return RecordingInput(
        storage_key=f"recordings/{uuid4()}",
        recorded_at=NOW,
        source=source,
        folder_id=folder_id,
        consent_confirmed_at=consent_confirmed_at,
    )


def refusal(call: Awaitable[object]) -> Failure | None:
    async def attempt() -> Failure | None:
        try:
            await call
        except UseCaseError as error:
            return error.code
        return None

    return asyncio.run(attempt())


def term(unit: Team, text: str, author: UUID) -> GlossaryTerm:
    return GlossaryTerm(
        term_id=uuid4(),
        workspace_id=unit.workspace,
        term=text,
        preferred_form=text,
        description="",
        created_by_user_id=author,
        source_meeting_id=None,
        created_at=NOW,
    )


# --- Creating a meeting ---


def test_extension_recording_without_consent_is_refused() -> None:
    # Arrange
    unit = team()
    # Act
    failure = refusal(
        unit.meetings.create(unit.owner, unit.workspace, recording(MeetingSource.EXTENSION), NOW)
    )
    # Assert
    assert failure is Failure.VALIDATION_ERROR


def test_recording_without_a_folder_goes_to_the_default_folder() -> None:
    # Arrange
    unit = team()
    # Act
    meeting = asyncio.run(unit.meetings.create(unit.member, unit.workspace, recording(), NOW))
    # Assert
    assert meeting.folder_id == unit.default_folder


def test_recording_into_an_unknown_folder_is_refused() -> None:
    # Arrange
    unit = team()
    # Act
    failure = refusal(
        unit.meetings.create(unit.owner, unit.workspace, recording(folder_id=uuid4()), NOW)
    )
    # Assert
    assert failure is Failure.VALIDATION_ERROR


def test_recording_is_scheduled_for_deletion_90_days_after_the_meeting() -> None:
    # Arrange
    unit = team()
    # Act
    meeting = asyncio.run(unit.meetings.create(unit.owner, unit.workspace, recording(), NOW))
    # Assert
    assert meeting.recording_delete_after == NOW + timedelta(days=90)


# --- Changing a meeting ---


def test_update_without_any_change_is_refused() -> None:
    # Arrange
    unit = team()
    # Act
    failure = refusal(unit.meetings.update(unit.owner, unit.meeting, NOW))
    # Assert
    assert failure is Failure.VALIDATION_ERROR


def test_renaming_a_meeting_is_audited() -> None:
    # Arrange
    unit = team()
    # Act
    asyncio.run(unit.meetings.update(unit.owner, unit.meeting, NOW, name="Sprint review"))
    # Assert
    assert [event.action for event in unit.audit.events] == [AuditAction.MEETING_RENAMED]


@NAMES_THE_API_ACCEPTS
def test_meeting_name_the_api_accepts_is_kept(name: str) -> None:
    # Arrange
    unit = team()
    # Act
    meeting = asyncio.run(unit.meetings.update(unit.owner, unit.meeting, NOW, name=name))
    # Assert
    assert meeting.name == name


@NAMES_THE_API_REFUSES
def test_meeting_name_the_api_refuses_is_refused(name: str) -> None:
    # Arrange
    unit = team()
    # Act
    failure = refusal(unit.meetings.update(unit.owner, unit.meeting, NOW, name=name))
    # Assert
    assert failure is Failure.VALIDATION_ERROR


def test_member_cannot_delete_someone_elses_meeting() -> None:
    # Arrange
    unit = team()
    # Act
    failure = refusal(unit.meetings.delete(unit.member, unit.meeting, NOW))
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


# --- Folders ---


def test_member_cannot_create_a_folder() -> None:
    # Arrange
    unit = team()
    # Act
    failure = refusal(unit.meetings.create_folder(unit.member, unit.workspace, "Design", NOW))
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


def test_folder_with_an_existing_name_is_refused() -> None:
    # Arrange
    unit = team()
    asyncio.run(unit.meetings.create_folder(unit.owner, unit.workspace, "Design", NOW))
    # Act
    failure = refusal(unit.meetings.create_folder(unit.owner, unit.workspace, " Design ", NOW))
    # Assert
    assert failure is Failure.FOLDER_EXISTS


def test_folder_name_with_a_control_character_is_refused() -> None:
    # Arrange
    unit = team()
    # Act
    failure = refusal(unit.meetings.create_folder(unit.owner, unit.workspace, "Des\x07ign", NOW))
    # Assert
    assert failure is Failure.VALIDATION_ERROR


@NAMES_THE_API_ACCEPTS
def test_folder_name_the_api_accepts_is_kept(name: str) -> None:
    # Arrange
    unit = team()
    # Act
    folder = asyncio.run(unit.meetings.create_folder(unit.owner, unit.workspace, name, NOW))
    # Assert
    assert folder.name == name


@NAMES_THE_API_REFUSES
def test_folder_name_the_api_refuses_is_refused(name: str) -> None:
    # Arrange
    unit = team()
    # Act
    failure = refusal(unit.meetings.create_folder(unit.owner, unit.workspace, name, NOW))
    # Assert
    assert failure is Failure.VALIDATION_ERROR


# --- Glossary ---


def test_term_differing_only_in_case_is_refused() -> None:
    # Arrange
    unit = team()
    asyncio.run(unit.meetings.add_term(unit.member, term(unit, "Whadio", unit.member)))
    # Act
    failure = refusal(unit.meetings.add_term(unit.owner, term(unit, "WHADIO", unit.owner)))
    # Assert
    assert failure is Failure.TERM_EXISTS


def test_member_cannot_delete_someone_elses_term() -> None:
    # Arrange
    unit = team()
    added = asyncio.run(unit.meetings.add_term(unit.owner, term(unit, "Whadio", unit.owner)))
    # Act
    failure = refusal(unit.meetings.delete_term(unit.member, unit.workspace, added.term_id))
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE


@NAMES_THE_API_ACCEPTS
def test_term_the_api_accepts_is_kept(name: str) -> None:
    # Arrange
    unit = team()
    # Act
    added = asyncio.run(unit.meetings.add_term(unit.member, term(unit, name, unit.member)))
    # Assert
    assert added.term == name


@NAMES_THE_API_REFUSES
def test_term_the_api_refuses_is_refused(name: str) -> None:
    # Arrange
    unit = team()
    # Act
    failure = refusal(unit.meetings.add_term(unit.member, term(unit, name, unit.member)))
    # Assert
    assert failure is Failure.VALIDATION_ERROR
