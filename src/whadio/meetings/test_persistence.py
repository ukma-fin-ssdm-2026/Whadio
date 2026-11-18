import asyncio
from uuid import UUID

import pytest

from ..access_policy.contracts import MeetingScope
from ..accounts.enums import LlmProvider, NotesTemplate
from .contracts import EvictionNotice
from .models import Meeting
from .persistence import GeneratedNotes, MeetingPersistence, PersistenceDependencies
from .services import MeetingChanges
from .test_services_unit import NOW, Team, team


class UnusedCapacity:
    async def capacity_workspaces(self, workspace_id: UUID) -> list[UUID]:
        raise NotImplementedError(workspace_id)


class UnusedEvictionAccess:
    async def eviction_recipients(self, scope: MeetingScope, uploader_id: UUID) -> dict[UUID, bool]:
        raise NotImplementedError(scope, uploader_id)


class UnusedEvictionNotices:
    async def enqueue(self, notice: EvictionNotice) -> None:
        raise NotImplementedError(notice)


def save_notes(unit: Team, proposed_name: str) -> Meeting:
    persistence = MeetingPersistence(
        PersistenceDependencies(
            unit.meetings,
            unit.repository,
            UnusedCapacity(),
            unit.audit,
            UnusedEvictionAccess(),
            UnusedEvictionNotices(),
        )
    )
    notes = GeneratedNotes(
        NotesTemplate.SUMMARY, LlmProvider.WHADIO, "test-model", "## Summary", proposed_name, ()
    )
    asyncio.run(persistence.save_generated_notes(unit.meeting, notes, None, NOW))
    return unit.repository.meeting_rows[unit.meeting]


NAMES_A_MEMBER_COULD_NOT_TYPE = pytest.mark.parametrize(
    "proposed_name",
    ["ㅤ", "⠀", "́", "Sprint\x9freview"],
    ids=["hangul-filler", "braille-blank", "combining-mark-alone", "c1-control"],
)


def test_displayable_proposed_name_replaces_the_timestamp_name() -> None:
    # Arrange
    unit = team()
    # Act
    meeting = save_notes(unit, "Sprint planning")
    # Assert
    assert meeting.name == "Sprint planning"


@NAMES_A_MEMBER_COULD_NOT_TYPE
def test_proposed_name_a_member_could_not_type_leaves_the_timestamp_name(
    proposed_name: str,
) -> None:
    # Arrange
    unit = team()
    # Act
    meeting = save_notes(unit, proposed_name)
    # Assert
    assert meeting.name == NOW.isoformat()


@NAMES_A_MEMBER_COULD_NOT_TYPE
def test_notes_are_saved_when_their_proposed_name_is_refused(proposed_name: str) -> None:
    # Arrange
    unit = team()
    # Act
    save_notes(unit, proposed_name)
    # Assert
    assert [note.content for note in unit.repository.note_rows] == ["## Summary"]


def test_name_a_member_gave_is_not_replaced_by_the_proposed_one() -> None:
    # Arrange
    unit = team()
    asyncio.run(
        unit.meetings.update(
            unit.owner,
            unit.meeting,
            NOW,
            MeetingChanges(name="Design review"),
        )
    )
    # Act
    meeting = save_notes(unit, "Sprint planning")
    # Assert
    assert meeting.name == "Design review"
