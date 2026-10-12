from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ..access_policy.services import IEvictionAccess
from ..accounts.enums import LlmProvider, NotesTemplate
from ..accounts.services import IWorkspaceCapacity
from ..audit.contracts import ContentEvent, IContentAuditWriter, NotesPreset
from ..audit.enums import AuditAction
from ..shared.errors import Failure, UseCaseError
from .contracts import ContextReference, EvictionNotice, IEvictionNotifier
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
    access: IEvictionAccess
    notifications: IEvictionNotifier


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
        self._access: IEvictionAccess = dependencies.access
        self._notifications: IEvictionNotifier = dependencies.notifications
        self._hosted_limit: int | None = hosted_limit

    async def ingest(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        recording: RecordingInput,
        now: datetime,
    ) -> Meeting:
        await self._meetings.folders(actor_id, workspace_id)
        overflow: list[Meeting] = []
        if self._hosted_limit is not None:
            workspaces = await self._capacity.capacity_workspaces(workspace_id)
            if not workspaces:
                raise UseCaseError(Failure.NOT_FOUND)
            overflow = await self._repository.capacity_overflow(workspaces, self._hosted_limit)
        meeting = await self._meetings.create(actor_id, workspace_id, recording, now)
        for old in overflow:
            scope = await self._repository.scope(old.meeting_id)
            recipients = await self._access.eviction_recipients(scope, actor_id)
            for recipient_id, can_read in recipients.items():
                await self._notifications.enqueue(
                    EvictionNotice(
                        old.meeting_id,
                        meeting.meeting_id,
                        recipient_id,
                        old.name if can_read else None,
                        now,
                    )
                )
            await self._repository.remove(old.meeting_id, now)
            await self._audit.write(
                ContentEvent(
                    actor_id,
                    scope.workspace_id,
                    old.meeting_id,
                    AuditAction.MEETING_EVICTED,
                    now,
                    triggering_meeting_id=meeting.meeting_id,
                )
            )
        return meeting

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
                    preset=NotesPreset(notes.preset.value),
                )
            )
