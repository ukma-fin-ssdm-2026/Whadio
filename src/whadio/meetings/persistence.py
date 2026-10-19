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
from .enums import RecordingStatus
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
class AssembledRecording:
    storage_key: str
    status: RecordingStatus
    sources: tuple[str, ...]


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
        """Create a meeting; one still being captured is not queued, so it evicts nothing."""
        await self._meetings.folders(actor_id, workspace_id)
        overflow = [] if recording.storage_key is None else await self._overflow(workspace_id)
        meeting = await self._meetings.create(actor_id, workspace_id, recording, now)
        await self._evict(overflow, actor_id, meeting.meeting_id, now)
        return meeting

    async def attach_recording(
        self,
        actor_id: UUID,
        meeting_id: UUID,
        recording: AssembledRecording,
        now: datetime,
    ) -> None:
        """Give a captured meeting its recording, making room for it as it starts to count."""
        workspace_id = await self._meetings.workspace_id(actor_id, meeting_id)
        overflow = await self._overflow(workspace_id)
        await self._meetings.attach_recording(meeting_id, recording.storage_key, recording.status)
        await self._repository.schedule_deletion(list(recording.sources), now)
        await self._evict(overflow, actor_id, meeting_id, now)

    async def _overflow(self, workspace_id: UUID) -> list[Meeting]:
        if self._hosted_limit is None:
            return []
        workspaces = await self._capacity.capacity_workspaces(workspace_id)
        if not workspaces:
            raise UseCaseError(Failure.NOT_FOUND)
        return await self._repository.capacity_overflow(workspaces, self._hosted_limit)

    async def _evict(
        self, overflow: list[Meeting], actor_id: UUID, triggering_id: UUID, now: datetime
    ) -> None:
        for old in overflow:
            scope = await self._repository.scope(old.meeting_id)
            recipients = await self._access.eviction_recipients(scope, actor_id)
            for recipient_id, can_read in recipients.items():
                await self._notifications.enqueue(
                    EvictionNotice(
                        old.meeting_id,
                        triggering_id,
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
                    triggering_meeting_id=triggering_id,
                )
            )

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
