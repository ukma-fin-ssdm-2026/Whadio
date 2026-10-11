from datetime import timedelta
from decimal import Decimal
from typing import Final, Protocol
from uuid import UUID

from ..accounts.enums import LlmProvider, NotesTemplate
from ..accounts.repositories import IWorkspaceSettings
from ..contracts.common import GlossaryEntry, Segment, Transcript
from ..contracts.notes import (
    MAX_CONTEXT_MEETINGS,
    ContextMeeting,
    MeetingBrief,
    NotesFailed,
    NotesPreset,
    NotesProvider,
    NotesReady,
    NotesRequested,
)
from ..contracts.results import JobStarted, ProcessingResult
from ..contracts.transcription import (
    AudioLink,
    TranscriptionFailed,
    TranscriptionRequested,
    TranscriptReady,
)
from ..meetings.enums import ProcessingState
from ..meetings.repositories import (
    GeneratedNotes,
    IMeetingPipeline,
    PipelineMeeting,
    StoredTranscript,
    TranscriptLine,
)
from ..shared.errors import Failure, UseCaseError
from ..shared.storage import IObjectStorage
from .enums import JobStatus, JobType
from .repositories import IJobRepository, Job

# Matches the delivery limit of the job queues: past it the broker dead-letters the message.
MAX_ATTEMPTS: Final = 5
# Long enough for a job that waits in the queue while the GPU host is down; an expired link is a
# retryable failure, and the retry gets a fresh one.
AUDIO_LINK_LIFETIME: Final = timedelta(hours=24)

JobRequest = TranscriptionRequested | NotesRequested

_PROVIDERS: Final = {
    NotesProvider.WHADIO: LlmProvider.WHADIO,
    NotesProvider.ANTHROPIC: LlmProvider.ANTHROPIC,
    NotesProvider.OPENAI: LlmProvider.OPENAI,
    NotesProvider.GOOGLE: LlmProvider.GOOGLE,
}


class IJobPublisher(Protocol):
    async def publish(self, request: JobRequest) -> None: ...


class ProcessingService:
    """Runs inside the caller's transaction and returns the job requests to publish.

    The caller publishes them only after committing, so a worker never answers a job the database
    does not have yet.
    """

    def __init__(
        self,
        jobs: IJobRepository,
        meetings: IMeetingPipeline,
        workspaces: IWorkspaceSettings,
        storage: IObjectStorage,
    ) -> None:
        self._jobs: IJobRepository = jobs
        self._meetings: IMeetingPipeline = meetings
        self._workspaces: IWorkspaceSettings = workspaces
        self._storage: IObjectStorage = storage

    async def queue_transcription(self, meeting_id: UUID) -> TranscriptionRequested:
        meeting = await self._meetings.meeting(meeting_id)
        if meeting is None:
            raise UseCaseError(Failure.NOT_FOUND)
        job_id = await self._jobs.add(meeting_id, JobType.TRANSCRIPTION)
        await self._meetings.set_state(meeting_id, ProcessingState.QUEUED)
        return await self._transcription_request(job_id, meeting)

    async def handle(self, result: ProcessingResult) -> list[JobRequest]:
        job = await self._jobs.lock(result.job_id)
        # A job of a deleted meeting is gone with it, and a finished job ignores a duplicate.
        if job is None or job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
            return []
        match result:
            case JobStarted():
                await self._jobs.mark_running(job.job_id, result.started_at)
                await self._meetings.set_state(job.meeting_id, ProcessingState.PROCESSING)
                return []
            case TranscriptReady():
                return await self._transcript_ready(job, result)
            case NotesReady():
                await self._notes_ready(job, result)
                return []
            case TranscriptionFailed() | NotesFailed():
                return await self._failed(job, result)

    async def _transcript_ready(self, job: Job, result: TranscriptReady) -> list[JobRequest]:
        await self._jobs.finish(job.job_id, JobStatus.SUCCEEDED, result.finished_at, None)
        await self._meetings.save_original_transcript(
            job.meeting_id,
            result.model_name,
            round(result.duration_seconds),
            StoredTranscript(
                language=result.transcript.language,
                speakers=result.transcript.speakers,
                lines=tuple(
                    TranscriptLine(
                        start_seconds=Decimal(str(segment.start_seconds)),
                        end_seconds=Decimal(str(segment.end_seconds)),
                        speaker=segment.speaker,
                        text=segment.text,
                    )
                    for segment in result.transcript.segments
                ),
            ),
        )
        meeting = await self._meetings.meeting(job.meeting_id)
        if meeting is None:
            return []
        notes_job = await self._jobs.add(job.meeting_id, JobType.NOTES)
        return [await self._notes_request(notes_job, meeting)]

    async def _notes_ready(self, job: Job, result: NotesReady) -> None:
        await self._jobs.finish(job.job_id, JobStatus.SUCCEEDED, result.finished_at, None)
        await self._meetings.save_notes(
            job.meeting_id,
            GeneratedNotes(
                template=NotesTemplate(result.preset.value),
                provider=_PROVIDERS[result.provider],
                model_name=result.model_name,
                content=result.content,
                proposed_name=result.proposed_name,
                context_meeting_ids=result.context_meeting_ids,
            ),
        )
        await self._meetings.set_state(job.meeting_id, ProcessingState.PROCESSED)

    async def _failed(
        self, job: Job, result: TranscriptionFailed | NotesFailed
    ) -> list[JobRequest]:
        meeting = await self._meetings.meeting(job.meeting_id)
        if meeting is not None and result.reason.retryable and job.attempts < MAX_ATTEMPTS:
            await self._jobs.requeue(job.job_id)
            if job.job_type is JobType.TRANSCRIPTION:
                return [await self._transcription_request(job.job_id, meeting)]
            return [await self._notes_request(job.job_id, meeting)]
        await self._jobs.finish(job.job_id, JobStatus.FAILED, result.finished_at, result.reason)
        await self._meetings.set_state(job.meeting_id, ProcessingState.FAILED)
        return []

    async def _transcription_request(
        self, job_id: UUID, meeting: PipelineMeeting
    ) -> TranscriptionRequested:
        if meeting.storage_path is None:
            raise UseCaseError(Failure.NOT_FOUND)
        link = self._storage.presign_get(meeting.storage_path, expires_in=AUDIO_LINK_LIFETIME)
        return TranscriptionRequested(
            job_id=job_id,
            meeting_id=meeting.meeting_id,
            # Lax validation turns the signed URL string into the contract's HttpUrl.
            audio=AudioLink.model_validate(
                {"url": link.url, "expires_at": link.expires_at}, strict=False
            ),
            language=None,
            glossary=await self._glossary(meeting.workspace_id),
        )

    async def _notes_request(self, job_id: UUID, meeting: PipelineMeeting) -> NotesRequested:
        transcript = await self._meetings.transcript(meeting.meeting_id)
        if transcript is None:
            raise UseCaseError(Failure.NOT_FOUND)
        template = await self._workspaces.default_template(meeting.workspace_id)
        context = await self._meetings.context(meeting, MAX_CONTEXT_MEETINGS)
        return NotesRequested(
            job_id=job_id,
            meeting_id=meeting.meeting_id,
            preset=NotesPreset((template or NotesTemplate.SUMMARY).value),
            meeting=MeetingBrief(
                name=None if meeting.name_is_generated else meeting.name,
                recorded_at=meeting.recorded_at,
            ),
            transcript=_contract_transcript(transcript),
            context=tuple(
                ContextMeeting(
                    meeting_id=other.meeting_id,
                    name=other.name,
                    recorded_at=other.recorded_at,
                    transcript=_contract_transcript(other.transcript),
                )
                for other in context
            ),
            glossary=await self._glossary(meeting.workspace_id),
        )

    async def _glossary(self, workspace_id: UUID) -> tuple[GlossaryEntry, ...]:
        return tuple(
            GlossaryEntry(
                term=item.term, preferred_form=item.preferred_form, description=item.description
            )
            for item in await self._meetings.glossary(workspace_id)
        )


def _contract_transcript(transcript: StoredTranscript) -> Transcript:
    return Transcript(
        language=transcript.language,
        speakers=transcript.speakers,
        segments=tuple(
            Segment(
                start_seconds=float(line.start_seconds),
                end_seconds=float(line.end_seconds),
                speaker=line.speaker,
                text=line.text,
            )
            for line in transcript.lines
        ),
    )
