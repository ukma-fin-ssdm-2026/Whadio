from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ..accounts.enums import LlmProvider, NotesTemplate
from ..accounts.services import IWorkspaceCapacity
from ..audit.contracts import ContentEvent, IContentAuditWriter
from ..audit.enums import AuditAction
from ..shared.errors import Failure, UseCaseError
from .contracts import ContextReference
from .models import Meeting, Note
from .repositories import IMeetingRepository
from .services import MeetingService, RecordingInput


@dataclass(frozen=True)
class GeneratedNotes:
    preset: NotesTemplate
    provider: LlmProvider
    model_name: str
    content: str
    proposed_name: str
    context: tuple[ContextReference, ...]


@dataclass(frozen=True)
class PersistenceDependencies:
    meetings: MeetingService
    repository: IMeetingRepository
    capacity: IWorkspaceCapacity
    audit: IContentAuditWriter


class MeetingPersistence:
    def __init__(
        self,
        dependencies: PersistenceDependencies,
        *,
        hosted_limit: int | None = None,
    ) -> None:
        if hosted_limit is not None and hosted_limit < 1:
            raise ValueError("The hosted capacity must be positive")
        self._meetings: MeetingService = dependencies.meetings
        self._repository: IMeetingRepository = dependencies.repository
        self._capacity: IWorkspaceCapacity = dependencies.capacity
        self._audit: IContentAuditWriter = dependencies.audit
        self._hosted_limit: int | None = hosted_limit

    async def ingest(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        recording: RecordingInput,
        now: datetime,
    ) -> Meeting:
        await self._meetings.folders(actor_id, workspace_id)
        if self._hosted_limit is not None:
            workspaces = await self._capacity.capacity_workspaces(workspace_id)
            if not workspaces:
                raise UseCaseError(Failure.NOT_FOUND)
            for old in await self._repository.capacity_overflow(workspaces, self._hosted_limit):
                scope = await self._repository.scope(old.meeting_id)
                await self._repository.remove(old.meeting_id, now)
                await self._audit.write(
                    ContentEvent(
                        actor_id,
                        scope.workspace_id,
                        old.meeting_id,
                        AuditAction.MEETING_EVICTED,
                        now,
                    )
                )
        return await self._meetings.create(actor_id, workspace_id, recording, now)

    async def save_generated_notes(
        self,
        meeting_id: UUID,
        notes: GeneratedNotes,
        requester_id: UUID | None,
        now: datetime,
    ) -> None:
        """Persist successful notes under Processing's job lock; it owns state and deduplication."""
        meeting = await self._repository.get(meeting_id, lock=True)
        scope = await self._repository.scope(meeting_id)
        note = Note(
            meeting_id=meeting_id,
            template=notes.preset,
            provider=notes.provider,
            model_name=notes.model_name,
            content=notes.content,
            created_at=now,
            created_by_user_id=requester_id,
        )
        await self._repository.save_notes(note, notes.context)
        if meeting.name_is_generated:
            meeting.name = notes.proposed_name
        await self._repository.save(meeting)
        if requester_id is not None:
            await self._audit.write(
                ContentEvent(
                    requester_id,
                    scope.workspace_id,
                    meeting_id,
                    AuditAction.NOTES_REGENERATED,
                    now,
                    subject_id=note.note_id,
                )
            )
