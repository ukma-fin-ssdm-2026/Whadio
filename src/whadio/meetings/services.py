from datetime import datetime
from typing import Protocol
from uuid import UUID

from ..accounts.enums import WorkspaceRole
from ..accounts.services import IWorkspaceMembership
from ..audit.services import IAuditWriter, MeetingMoved
from ..shared.errors import Failure, UseCaseError
from .enums import AccessMode, ProcessingState
from .repositories import (
    ContextCandidate,
    GeneratedNotes,
    GlossaryItem,
    IFolderRepository,
    IMeetingPipelineRepository,
    MeetingSummary,
    PipelineMeeting,
    StoredTranscript,
)


class FolderService:
    def __init__(
        self,
        repository: IFolderRepository,
        memberships: IWorkspaceMembership,
        audit: IAuditWriter,
    ) -> None:
        self._repository: IFolderRepository = repository
        self._memberships: IWorkspaceMembership = memberships
        self._audit: IAuditWriter = audit

    async def delete_folder(
        self, actor_id: UUID, workspace_id: UUID, folder_id: UUID, now: datetime
    ) -> None:
        """Move, audit and delete using collaborators sharing the caller's transaction."""
        role = await self._memberships.lock_role(workspace_id, actor_id)
        if role is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if role not in (WorkspaceRole.OWNER, WorkspaceRole.MODERATOR):
            raise UseCaseError(Failure.INSUFFICIENT_ROLE)
        folder = await self._repository.folder(workspace_id, folder_id)
        if folder is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if folder.is_default:
            raise UseCaseError(Failure.DEFAULT_FOLDER)
        destination = await self._repository.default_folder(workspace_id)
        if destination is None:
            raise UseCaseError(Failure.NOT_FOUND)
        for meeting_id in await self._repository.move_meetings(folder_id, destination.folder_id):
            await self._audit.write(
                MeetingMoved(
                    actor_id,
                    workspace_id,
                    meeting_id,
                    now,
                    folder_id,
                    destination.folder_id,
                )
            )
        await self._repository.remove_folder(folder_id)


class IMeetingPipeline(Protocol):
    async def meeting(self, meeting_id: UUID, /) -> PipelineMeeting | None: ...

    async def lock(self, meeting_id: UUID, /) -> PipelineMeeting | None: ...

    async def has_transcript(self, meeting_id: UUID, /) -> bool: ...

    async def set_state(self, meeting_id: UUID, state: ProcessingState, /) -> None: ...

    async def save_original_transcript(
        self,
        meeting_id: UUID,
        model_name: str,
        duration_seconds: int,
        transcript: StoredTranscript,
        /,
    ) -> None: ...

    async def transcript(self, meeting_id: UUID, /) -> StoredTranscript | None: ...

    async def context_summaries(
        self, meeting: PipelineMeeting, limit: int, /
    ) -> list[MeetingSummary]: ...

    async def context(self, meeting: PipelineMeeting, limit: int, /) -> list[ContextCandidate]: ...

    async def glossary(self, workspace_id: UUID, /) -> list[GlossaryItem]: ...

    async def save_notes(self, meeting: PipelineMeeting, notes: GeneratedNotes, /) -> None: ...


class MeetingPipelineService:
    """Shares the caller's transaction through the repository's session."""

    def __init__(self, repository: IMeetingPipelineRepository) -> None:
        self._repository: IMeetingPipelineRepository = repository

    async def meeting(self, meeting_id: UUID) -> PipelineMeeting | None:
        return await self._repository.meeting(meeting_id)

    async def lock(self, meeting_id: UUID) -> PipelineMeeting | None:
        return await self._repository.lock(meeting_id)

    async def has_transcript(self, meeting_id: UUID) -> bool:
        return await self._repository.has_transcript(meeting_id)

    async def set_state(self, meeting_id: UUID, state: ProcessingState) -> None:
        await self._repository.set_state(meeting_id, state)

    async def save_original_transcript(
        self, meeting_id: UUID, model_name: str, duration_seconds: int, transcript: StoredTranscript
    ) -> None:
        await self._repository.save_original_transcript(
            meeting_id, model_name, duration_seconds, transcript
        )

    async def transcript(self, meeting_id: UUID) -> StoredTranscript | None:
        return await self._repository.transcript(meeting_id)

    async def context_summaries(self, meeting: PipelineMeeting, limit: int) -> list[MeetingSummary]:
        # Processed meetings of the same folder; restricted ones never reach another meeting's
        # notes (FR-019). One extra row makes up for the meeting itself.
        others = await self._repository.summaries(
            meeting.folder_id, AccessMode.WORKSPACE, ProcessingState.PROCESSED, limit + 1
        )
        return [other for other in others if other.meeting_id != meeting.meeting_id][:limit]

    async def context(self, meeting: PipelineMeeting, limit: int) -> list[ContextCandidate]:
        candidates: list[ContextCandidate] = []
        for other in await self.context_summaries(meeting, limit):
            transcript = await self._repository.transcript(other.meeting_id)
            if transcript is not None:
                candidates.append(
                    ContextCandidate(other.meeting_id, other.name, other.recorded_at, transcript)
                )
        return candidates

    async def glossary(self, workspace_id: UUID) -> list[GlossaryItem]:
        return await self._repository.glossary(workspace_id)

    async def save_notes(self, meeting: PipelineMeeting, notes: GeneratedNotes) -> None:
        await self._repository.save_notes(meeting.meeting_id, notes)
        # A name a member gave the meeting is never replaced by a generated one (FR-033).
        if meeting.name_is_generated:
            await self._repository.rename(meeting.meeting_id, notes.proposed_name)
