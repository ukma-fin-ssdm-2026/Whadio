from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import Select, delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..accounts.enums import LlmProvider, NotesTemplate
from .enums import AccessMode, ProcessingState, RevisionType
from .models import (
    Folder,
    GlossaryTerm,
    Meeting,
    Note,
    NoteContextMeeting,
    Speaker,
    Transcript,
    TranscriptRevision,
    TranscriptSegment,
)


class IFolderRepository(Protocol):
    async def folder(self, workspace_id: UUID, folder_id: UUID) -> Folder | None: ...

    async def default_folder(self, workspace_id: UUID) -> Folder | None: ...

    async def move_meetings(self, folder_id: UUID, destination_id: UUID) -> list[UUID]: ...

    async def remove_folder(self, folder_id: UUID) -> None: ...


class FolderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def folder(self, workspace_id: UUID, folder_id: UUID) -> Folder | None:
        return await self._session.scalar(
            select(Folder)
            .where(Folder.workspace_id == workspace_id, Folder.folder_id == folder_id)
            .with_for_update()
        )

    async def default_folder(self, workspace_id: UUID) -> Folder | None:
        return await self._session.scalar(
            select(Folder)
            .where(Folder.workspace_id == workspace_id, Folder.is_default)
            .with_for_update()
        )

    async def move_meetings(self, folder_id: UUID, destination_id: UUID) -> list[UUID]:
        return list(
            await self._session.scalars(
                update(Meeting)
                .where(Meeting.folder_id == folder_id)
                .values(folder_id=destination_id)
                .returning(Meeting.meeting_id)
            )
        )

    async def remove_folder(self, folder_id: UUID) -> None:
        await self._session.execute(delete(Folder).where(Folder.folder_id == folder_id))


# --- The meeting pipeline, as Processing sees it ---


@dataclass(frozen=True, slots=True)
class PipelineMeeting:
    meeting_id: UUID
    workspace_id: UUID
    folder_id: UUID
    storage_path: str | None
    name: str
    name_is_generated: bool
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class MeetingSummary:
    meeting_id: UUID
    name: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class TranscriptLine:
    start_seconds: Decimal
    end_seconds: Decimal
    speaker: str | None
    text: str


@dataclass(frozen=True, slots=True)
class StoredTranscript:
    language: str
    speakers: tuple[str, ...]
    lines: tuple[TranscriptLine, ...]


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    meeting_id: UUID
    name: str
    recorded_at: datetime
    transcript: StoredTranscript


@dataclass(frozen=True, slots=True)
class GlossaryItem:
    term: str
    preferred_form: str
    description: str


@dataclass(frozen=True, slots=True)
class GeneratedNotes:
    template: NotesTemplate
    provider: LlmProvider
    model_name: str
    content: str
    proposed_name: str
    context: tuple[MeetingSummary, ...]


class IMeetingPipelineRepository(Protocol):
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

    async def summaries(
        self, folder_id: UUID, access_mode: AccessMode, state: ProcessingState, limit: int, /
    ) -> list[MeetingSummary]: ...

    async def glossary(self, workspace_id: UUID, /) -> list[GlossaryItem]: ...

    async def save_notes(self, meeting_id: UUID, notes: GeneratedNotes, /) -> None: ...

    async def rename(self, meeting_id: UUID, name: str, /) -> None: ...


class MeetingPipelineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def meeting(self, meeting_id: UUID) -> PipelineMeeting | None:
        return await self._pipeline_meeting(_meeting_with_workspace(meeting_id))

    async def lock(self, meeting_id: UUID) -> PipelineMeeting | None:
        return await self._pipeline_meeting(
            _meeting_with_workspace(meeting_id).with_for_update(of=Meeting)
        )

    async def _pipeline_meeting(self, statement: Select[Meeting, UUID]) -> PipelineMeeting | None:
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None
        found, workspace_id = row
        return PipelineMeeting(
            meeting_id=found.meeting_id,
            workspace_id=workspace_id,
            folder_id=found.folder_id,
            storage_path=found.storage_path,
            name=found.name,
            name_is_generated=found.name_is_generated,
            recorded_at=found.recorded_at,
        )

    async def has_transcript(self, meeting_id: UUID) -> bool:
        return bool(
            await self._session.scalar(select(exists().where(Transcript.meeting_id == meeting_id)))
        )

    async def set_state(self, meeting_id: UUID, state: ProcessingState) -> None:
        await self._session.execute(
            update(Meeting).where(Meeting.meeting_id == meeting_id).values(processing_state=state)
        )

    async def save_original_transcript(
        self, meeting_id: UUID, model_name: str, duration_seconds: int, transcript: StoredTranscript
    ) -> None:
        transcript_id, revision_id = uuid4(), uuid4()
        # The transcript points at its current revision through a deferred foreign key, so both
        # rows go in before the transaction checks it.
        self._session.add(
            Transcript(
                transcript_id=transcript_id,
                meeting_id=meeting_id,
                language=transcript.language,
                model_name=model_name,
                current_revision_id=revision_id,
            )
        )
        await self._session.flush()
        revision = TranscriptRevision(
            revision_id=revision_id,
            transcript_id=transcript_id,
            revision_type=RevisionType.ORIGINAL,
        )
        self._session.add(revision)
        await self._session.flush()
        speakers = {
            label: Speaker(revision_id=revision.revision_id, display_name=label)
            for label in transcript.speakers
        }
        self._session.add_all(speakers.values())
        await self._session.flush()
        self._session.add_all(
            TranscriptSegment(
                revision_id=revision.revision_id,
                speaker_id=None if line.speaker is None else speakers[line.speaker].speaker_id,
                start_time_seconds=line.start_seconds,
                end_time_seconds=line.end_seconds,
                text=line.text,
            )
            for line in transcript.lines
        )
        await self._session.execute(
            update(Meeting)
            .where(Meeting.meeting_id == meeting_id)
            .values(duration_seconds=duration_seconds)
        )
        await self._session.flush()

    async def transcript(self, meeting_id: UUID) -> StoredTranscript | None:
        found = await self._session.scalar(
            select(Transcript).where(Transcript.meeting_id == meeting_id)
        )
        if found is None:
            return None
        speakers = {
            speaker.speaker_id: speaker.display_name
            for speaker in await self._session.scalars(
                select(Speaker).where(Speaker.revision_id == found.current_revision_id)
            )
        }
        segments = await self._session.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.revision_id == found.current_revision_id)
            .order_by(TranscriptSegment.start_time_seconds)
        )
        lines = tuple(
            TranscriptLine(
                start_seconds=segment.start_time_seconds,
                end_seconds=segment.end_time_seconds,
                speaker=None if segment.speaker_id is None else speakers[segment.speaker_id],
                text=segment.text,
            )
            for segment in segments
        )
        # Labels in order of first appearance, as the transcription contract lists them.
        order = list(dict.fromkeys(line.speaker for line in lines if line.speaker is not None))
        unheard = sorted(set(speakers.values()) - set(order))
        return StoredTranscript(language=found.language, speakers=(*order, *unheard), lines=lines)

    async def summaries(
        self, folder_id: UUID, access_mode: AccessMode, state: ProcessingState, limit: int
    ) -> list[MeetingSummary]:
        rows = await self._session.execute(
            select(Meeting.meeting_id, Meeting.name, Meeting.recorded_at)
            .where(
                Meeting.folder_id == folder_id,
                Meeting.access_mode == access_mode,
                Meeting.processing_state == state,
            )
            .order_by(Meeting.recorded_at.desc(), Meeting.meeting_id)
            .limit(limit)
        )
        return [
            MeetingSummary(meeting_id, name, recorded_at) for meeting_id, name, recorded_at in rows
        ]

    async def glossary(self, workspace_id: UUID) -> list[GlossaryItem]:
        return [
            GlossaryItem(term.term, term.preferred_form, term.description)
            for term in await self._session.scalars(
                select(GlossaryTerm)
                .where(GlossaryTerm.workspace_id == workspace_id)
                .order_by(GlossaryTerm.term)
            )
        ]

    async def save_notes(self, meeting_id: UUID, notes: GeneratedNotes) -> None:
        note = Note(
            meeting_id=meeting_id,
            template=notes.template,
            content=notes.content,
            model_name=notes.model_name,
            provider=notes.provider,
        )
        self._session.add(note)
        await self._session.flush()
        self._session.add_all(
            NoteContextMeeting(
                note_id=note.note_id,
                context_meeting_id=context.meeting_id,
                context_meeting_name_snapshot=context.name,
            )
            for context in notes.context
        )
        await self._session.flush()

    async def rename(self, meeting_id: UUID, name: str) -> None:
        await self._session.execute(
            update(Meeting).where(Meeting.meeting_id == meeting_id).values(name=name)
        )


def _meeting_with_workspace(meeting_id: UUID) -> Select[Meeting, UUID]:
    return (
        select(Meeting, Folder.workspace_id)
        .join(Folder, Folder.folder_id == Meeting.folder_id)
        .where(Meeting.meeting_id == meeting_id)
    )
