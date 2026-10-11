from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final, Protocol
from uuid import UUID

from ..accounts.enums import LlmProvider, NotesTemplate
from ..accounts.services import IWorkspaceSettings
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
    PipelineMeeting,
    StoredTranscript,
    TranscriptLine,
)
from ..meetings.services import IMeetingPipeline
from ..shared.errors import Failure, UseCaseError
from ..shared.storage import IObjectStorage
from .enums import JobStatus, JobType
from .repositories import IJobRepository, Job

# Matches the delivery limit of the job queues: past it the broker dead-letters the message.
MAX_ATTEMPTS: Final = 5
# Long enough for a job that waits in the queue while the GPU host is down; an expired link is a
# retryable failure, and the retry gets a fresh one.
AUDIO_LINK_LIFETIME: Final = timedelta(hours=24)
DEAD_LETTERED: Final = "dead_lettered"

JobRequest = TranscriptionRequested | NotesRequested

_PROVIDERS: Final = {
    NotesProvider.WHADIO: LlmProvider.WHADIO,
    NotesProvider.ANTHROPIC: LlmProvider.ANTHROPIC,
    NotesProvider.OPENAI: LlmProvider.OPENAI,
    NotesProvider.GOOGLE: LlmProvider.GOOGLE,
}


class IJobPublisher(Protocol):
    async def publish(self, request: JobRequest) -> None: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


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
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._jobs: IJobRepository = jobs
        self._meetings: IMeetingPipeline = meetings
        self._workspaces: IWorkspaceSettings = workspaces
        self._storage: IObjectStorage = storage
        self._now: Callable[[], datetime] = now

    async def queue_transcription(self, meeting_id: UUID) -> TranscriptionRequested:
        # The lock serializes two submissions of the same meeting, so only one finds no job.
        meeting = await self._meetings.lock(meeting_id)
        if meeting is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if await self._meetings.has_transcript(meeting_id) or await self._jobs.has_unfinished(
            meeting_id, JobType.TRANSCRIPTION
        ):
            raise UseCaseError(Failure.ALREADY_PROCESSED)
        job_id = await self._jobs.add(meeting_id, JobType.TRANSCRIPTION)
        await self._meetings.set_state(meeting_id, ProcessingState.QUEUED)
        return await self._transcription_request(job_id, meeting)

    async def handle(self, result: ProcessingResult) -> list[JobRequest]:
        """Drop a result that does not fit its job's state, type or meeting, changing nothing."""
        job = await self._jobs.lock(result.job_id)
        # A job of a deleted meeting is gone with it.
        if (
            job is None
            or job.meeting_id != result.meeting_id
            or job.job_type != _job_type(result)
            or job.status not in _accepted_statuses(result)
        ):
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

    async def dead_lettered(self, job_id: UUID) -> None:
        job = await self._jobs.lock(job_id)
        if job is None or job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
            return
        await self._jobs.finish(job.job_id, JobStatus.FAILED, self._now(), DEAD_LETTERED)
        await self._meetings.set_state(job.meeting_id, ProcessingState.FAILED)

    async def _transcript_ready(self, job: Job, result: TranscriptReady) -> list[JobRequest]:
        meeting = await self._meetings.lock(job.meeting_id)
        if meeting is None:
            return []
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
        notes_job = await self._jobs.add(job.meeting_id, JobType.NOTES)
        return [await self._notes_request(notes_job, meeting)]

    async def _notes_ready(self, job: Job, result: NotesReady) -> None:
        # Locked, the meeting cannot be renamed by a member between the name check and the save.
        meeting = await self._meetings.lock(job.meeting_id)
        if meeting is None:
            return
        sent = {
            other.meeting_id: other
            for other in await self._meetings.context_summaries(meeting, MAX_CONTEXT_MEETINGS)
        }
        await self._jobs.finish(job.job_id, JobStatus.SUCCEEDED, result.finished_at, None)
        await self._meetings.save_notes(
            meeting,
            GeneratedNotes(
                template=NotesTemplate(result.preset.value),
                provider=_PROVIDERS[result.provider],
                model_name=result.model_name,
                content=result.content,
                proposed_name=result.proposed_name,
                # The worker may name only meetings it was sent, each once.
                context=tuple(
                    sent[context_id]
                    for context_id in dict.fromkeys(result.context_meeting_ids)
                    if context_id in sent
                ),
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
            preset=NotesPreset(template.value),
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


def _job_type(result: ProcessingResult) -> JobType:
    match result:
        case JobStarted():
            return JobType(result.kind.value)
        case TranscriptReady() | TranscriptionFailed():
            return JobType.TRANSCRIPTION
        case NotesReady() | NotesFailed():
            return JobType.NOTES


def _accepted_statuses(result: ProcessingResult) -> frozenset[JobStatus]:
    match result:
        case JobStarted():
            return frozenset({JobStatus.QUEUED})
        case TranscriptReady() | NotesReady():
            return frozenset({JobStatus.QUEUED, JobStatus.RUNNING})
        case TranscriptionFailed() | NotesFailed():
            # Until a result names its attempt, a failure counts only for the running one: a
            # redelivered or late failure must not requeue the job a second time.
            return frozenset({JobStatus.RUNNING})


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
