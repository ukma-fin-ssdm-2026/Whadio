from dataclasses import dataclass
from datetime import datetime, timedelta
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
    NotesFailure,
    NotesPreset,
    NotesProvider,
    NotesReady,
    NotesRequested,
)
from ..contracts.results import JobStarted, ProcessingResult
from ..contracts.transcription import (
    AudioLink,
    TranscriptionFailed,
    TranscriptionFailure,
    TranscriptionRequested,
    TranscriptReady,
)
from ..meetings.contracts import (
    ContextReference,
    ContextTranscript,
    InitialSegment,
    InitialSpeaker,
    InitialTranscript,
    PipelineMeeting,
    ProcessingUpdate,
    QueuedNotes,
    TranscriptVersion,
)
from ..meetings.enums import ProcessingFailure, ProcessingState
from ..meetings.models import GlossaryTerm, Meeting
from ..meetings.persistence import GeneratedNotes
from ..shared.errors import Failure, UseCaseError
from ..shared.storage import IObjectStorage
from .enums import JobStatus, JobType, ProcessingOutcome
from .repositories import IJobRepository, Job
from .speakers import ISpeakerTimeline, resolve_speaker_names

# Matches the delivery limit of the job queues: past it the broker dead-letters the message.
MAX_ATTEMPTS: Final = 5
# Long enough for a job that waits in the queue while the GPU host is down; an expired link is a
# retryable failure, and the retry gets a fresh one.
AUDIO_LINK_LIFETIME: Final = timedelta(hours=24)
DEAD_LETTERED: Final = "dead_lettered"
TRANSCRIPT_EXISTS: Final = "transcript_exists"
UNPUBLISHABLE: Final = "unpublishable"

JobRequest = TranscriptionRequested | NotesRequested

_PROVIDERS: Final = {
    NotesProvider.WHADIO: LlmProvider.WHADIO,
    NotesProvider.ANTHROPIC: LlmProvider.ANTHROPIC,
    NotesProvider.OPENAI: LlmProvider.OPENAI,
    NotesProvider.GOOGLE: LlmProvider.GOOGLE,
}

# What the meeting shows for a job that failed for good; anything not listed is the job type's
# general failure.
_FAILURES: Final[dict[TranscriptionFailure | NotesFailure, ProcessingFailure]] = {
    TranscriptionFailure.TIMED_OUT: ProcessingFailure.PROCESSING_TIMEOUT,
    NotesFailure.TIMED_OUT: ProcessingFailure.PROCESSING_TIMEOUT,
    NotesFailure.PROVIDER_UNAVAILABLE: ProcessingFailure.PROVIDER_UNAVAILABLE,
    NotesFailure.PROVIDER_RATE_LIMITED: ProcessingFailure.PROVIDER_UNAVAILABLE,
    NotesFailure.PROVIDER_AUTH_FAILED: ProcessingFailure.PROVIDER_REJECTED,
    NotesFailure.PROVIDER_REFUSED: ProcessingFailure.PROVIDER_REJECTED,
    NotesFailure.PROVIDER_REJECTED_REQUEST: ProcessingFailure.PROVIDER_REJECTED,
}
_GENERAL_FAILURES: Final = {
    JobType.TRANSCRIPTION: ProcessingFailure.TRANSCRIPTION_FAILED,
    JobType.NOTES: ProcessingFailure.NOTES_FAILED,
}


class IJobPublisher(Protocol):
    async def publish(self, request: JobRequest) -> None: ...


class IPipelineMeetings(Protocol):
    """The Meetings service methods Processing uses; none of them checks a member's access."""

    async def pipeline_meeting(
        self, meeting_id: UUID, /, *, lock: bool = False
    ) -> PipelineMeeting | None: ...

    async def current_transcript(self, meeting_id: UUID, /) -> TranscriptVersion | None: ...

    async def notes_context(self, meeting: Meeting, limit: int, /) -> list[ContextTranscript]: ...

    async def workspace_glossary(self, workspace_id: UUID, /) -> list[GlossaryTerm]: ...

    async def save_initial_transcript(
        self, meeting_id: UUID, result: InitialTranscript, now: datetime, /
    ) -> TranscriptVersion: ...

    async def save_processing_state(
        self, meeting_id: UUID, update: ProcessingUpdate, /
    ) -> None: ...


class IGeneratedNotes(Protocol):
    async def save_generated_notes(
        self, meeting_id: UUID, notes: GeneratedNotes, requester_id: UUID | None, now: datetime, /
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ProcessingNotice:
    recipient_id: UUID
    meeting_id: UUID
    meeting_name: str
    outcome: ProcessingOutcome


class IProcessingNotifier(Protocol):
    async def notify(self, notice: ProcessingNotice, /) -> None:
        """Add the notice in the caller's transaction; a meeting's repeated outcome is dropped."""
        ...


class IMeetingReaders(Protocol):
    async def can_read(self, user_id: UUID, meeting_id: UUID, /) -> bool: ...


@dataclass(frozen=True)
class ProcessingCollaborators:
    jobs: IJobRepository
    meetings: IPipelineMeetings
    notes: IGeneratedNotes
    workspaces: IWorkspaceSettings
    storage: IObjectStorage
    speaker_timeline: ISpeakerTimeline
    notices: IProcessingNotifier
    readers: IMeetingReaders


class ProcessingService:
    """Runs inside the caller's transaction. Queueing only records a job; `publish_next` sends
    it, in a later transaction, so a job is never published before its row is committed and
    never lost when a publish fails.

    It is also Meetings' `IMeetingProcessing`.
    """

    def __init__(self, collaborators: ProcessingCollaborators) -> None:
        self._jobs: IJobRepository = collaborators.jobs
        self._meetings: IPipelineMeetings = collaborators.meetings
        self._notes: IGeneratedNotes = collaborators.notes
        self._workspaces: IWorkspaceSettings = collaborators.workspaces
        self._storage: IObjectStorage = collaborators.storage
        self._speaker_timeline: ISpeakerTimeline = collaborators.speaker_timeline
        self._notices: IProcessingNotifier = collaborators.notices
        self._readers: IMeetingReaders = collaborators.readers

    async def queue_transcription(self, meeting_id: UUID) -> None:
        # The lock serializes two submissions of the same meeting, so only one finds no job.
        if await self._meetings.pipeline_meeting(meeting_id, lock=True) is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if await self._meetings.current_transcript(
            meeting_id
        ) is not None or await self._jobs.has_unfinished(meeting_id, JobType.TRANSCRIPTION):
            raise UseCaseError(Failure.ALREADY_PROCESSED)
        await self._jobs.add(meeting_id, JobType.TRANSCRIPTION)
        await self._meetings.save_processing_state(
            meeting_id, ProcessingUpdate(ProcessingState.QUEUED)
        )

    async def queue_notes(
        self,
        meeting_id: UUID,
        requester_id: UUID,
        preset: NotesTemplate | None,
        *,
        use_builtin_model: bool,
        now: datetime,
    ) -> QueuedNotes:
        # Regenerating notes is outside the MVP.
        del meeting_id, requester_id, preset, use_builtin_model, now
        raise UseCaseError(Failure.INTEGRATION_UNAVAILABLE)

    async def publish_next(self, publisher: IJobPublisher, now: datetime) -> bool:
        """Publish the oldest unpublished job; False when none is left.

        A failed publish raises, and the caller's rollback leaves the job for the next round. A
        commit that fails after the publish sends the job twice, which `handle` absorbs.
        """
        job = await self._jobs.next_unpublished()
        if job is None:
            return False
        try:
            request, context = await self._request(job)
        except UseCaseError:
            # The recording or the transcript is gone, which no retry brings back.
            await self._finally_failed(job, now, UNPUBLISHABLE, _GENERAL_FAILURES[job.job_type])
            return True
        await publisher.publish(request)
        await self._jobs.mark_published(job.job_id, now, context)
        return True

    async def handle(self, result: ProcessingResult) -> None:
        """Drop a result that does not fit its job's state, type or meeting, changing nothing."""
        job = await self._jobs.lock(result.job_id)
        # A job of a deleted meeting is gone with it.
        if (
            job is None
            or job.meeting_id != result.meeting_id
            or job.job_type != _job_type(result)
            or job.status not in _accepted_statuses(result)
        ):
            return
        match result:
            case JobStarted():
                await self._jobs.mark_running(job.job_id, result.started_at)
                await self._meetings.save_processing_state(
                    job.meeting_id, ProcessingUpdate(ProcessingState.PROCESSING)
                )
            case TranscriptReady():
                await self._transcript_ready(job, result)
            case NotesReady():
                await self._notes_ready(job, result)
            case TranscriptionFailed() | NotesFailed():
                await self._failed(job, result)

    async def dead_lettered(self, job_id: UUID, now: datetime) -> None:
        job = await self._jobs.lock(job_id)
        if job is None or job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
            return
        await self._finally_failed(job, now, DEAD_LETTERED, _GENERAL_FAILURES[job.job_type])

    async def _transcript_ready(self, job: Job, result: TranscriptReady) -> None:
        if await self._meetings.pipeline_meeting(job.meeting_id, lock=True) is None:
            return
        if await self._meetings.current_transcript(job.meeting_id) is not None:
            # Meetings keeps one original transcript; another job's result cannot replace it.
            await self._jobs.finish(
                job.job_id, JobStatus.FAILED, result.finished_at, TRANSCRIPT_EXISTS
            )
            return
        await self._jobs.finish(job.job_id, JobStatus.SUCCEEDED, result.finished_at, None)
        # The label stays the key the segments refer to; only what members see is the name.
        names = resolve_speaker_names(
            await self._speaker_timeline.speaker_events(job.meeting_id),
            result.transcript.segments,
            result.duration_seconds,
        )
        await self._meetings.save_initial_transcript(
            job.meeting_id,
            InitialTranscript(
                job_id=job.job_id,
                language=result.transcript.language,
                model_name=result.model_name,
                speakers=tuple(
                    InitialSpeaker(key=label, display_name=names.get(label, label))
                    for label in result.transcript.speakers
                ),
                segments=tuple(
                    InitialSegment(
                        speaker_key=segment.speaker,
                        start_seconds=Decimal(str(segment.start_seconds)),
                        end_seconds=Decimal(str(segment.end_seconds)),
                        text=segment.text,
                    )
                    for segment in result.transcript.segments
                ),
            ),
            result.finished_at,
        )
        await self._meetings.save_processing_state(
            job.meeting_id,
            ProcessingUpdate(
                ProcessingState.PROCESSING, duration_seconds=round(result.duration_seconds)
            ),
        )
        await self._jobs.add(job.meeting_id, JobType.NOTES)

    async def _notes_ready(self, job: Job, result: NotesReady) -> None:
        # Locked, the meeting cannot be renamed by a member between the name check and the save.
        if await self._meetings.pipeline_meeting(job.meeting_id, lock=True) is None:
            return
        # The names as they were sent, so the note keeps them after a rename or deletion.
        sent = {reference.meeting_id: reference.name for reference in job.sent_context}
        await self._jobs.finish(job.job_id, JobStatus.SUCCEEDED, result.finished_at, None)
        await self._notes.save_generated_notes(
            job.meeting_id,
            GeneratedNotes(
                preset=NotesTemplate(result.preset.value),
                provider=_PROVIDERS[result.provider],
                model_name=result.model_name,
                content=result.content,
                proposed_name=result.proposed_name,
                # The worker may name only meetings it was sent, each once.
                context=tuple(
                    ContextReference(context_id, sent[context_id])
                    for context_id in dict.fromkeys(result.context_meeting_ids)
                    if context_id in sent
                ),
            ),
            None,
            result.finished_at,
        )
        await self._meetings.save_processing_state(
            job.meeting_id, ProcessingUpdate(ProcessingState.PROCESSED)
        )
        await self._notify_uploader(job.meeting_id, ProcessingOutcome.FINISHED)

    async def _failed(self, job: Job, result: TranscriptionFailed | NotesFailed) -> None:
        if result.reason.retryable and job.attempts < MAX_ATTEMPTS:
            await self._jobs.requeue(job.job_id)
            return
        await self._finally_failed(
            job,
            result.finished_at,
            result.reason,
            _FAILURES.get(result.reason, _GENERAL_FAILURES[job.job_type]),
        )

    async def _finally_failed(
        self, job: Job, finished_at: datetime, reason: str, failure: ProcessingFailure
    ) -> None:
        await self._jobs.finish(job.job_id, JobStatus.FAILED, finished_at, reason)
        await self._meetings.save_processing_state(
            job.meeting_id, ProcessingUpdate(ProcessingState.FAILED, failure)
        )
        await self._notify_uploader(job.meeting_id, ProcessingOutcome.FAILED)

    async def _notify_uploader(self, meeting_id: UUID, outcome: ProcessingOutcome) -> None:
        # Read after the save: generated notes may have renamed the meeting.
        found = await self._meetings.pipeline_meeting(meeting_id)
        if found is None or not await self._readers.can_read(
            found.meeting.created_by_user_id, meeting_id
        ):
            return
        meeting = found.meeting
        await self._notices.notify(
            ProcessingNotice(meeting.created_by_user_id, meeting_id, meeting.name, outcome)
        )

    async def _request(self, job: Job) -> tuple[JobRequest, tuple[ContextReference, ...]]:
        found = await self._meetings.pipeline_meeting(job.meeting_id)
        if found is None:
            raise UseCaseError(Failure.NOT_FOUND)
        if job.job_type is JobType.TRANSCRIPTION:
            return await self._transcription_request(job.job_id, found), ()
        return await self._notes_request(job.job_id, found)

    async def _transcription_request(
        self, job_id: UUID, found: PipelineMeeting
    ) -> TranscriptionRequested:
        if found.meeting.storage_path is None:
            raise UseCaseError(Failure.NOT_FOUND)
        link = self._storage.presign_get(found.meeting.storage_path, expires_in=AUDIO_LINK_LIFETIME)
        return TranscriptionRequested(
            job_id=job_id,
            meeting_id=found.meeting.meeting_id,
            # Lax validation turns the signed URL string into the contract's HttpUrl.
            audio=AudioLink.model_validate(
                {"url": link.url, "expires_at": link.expires_at}, strict=False
            ),
            language=None,
            glossary=await self._glossary(found.workspace_id),
        )

    async def _notes_request(
        self, job_id: UUID, found: PipelineMeeting
    ) -> tuple[NotesRequested, tuple[ContextReference, ...]]:
        """The request, and the context meetings it sends, as `handle` checks the notes against."""
        meeting = found.meeting
        transcript = await self._meetings.current_transcript(meeting.meeting_id)
        if transcript is None:
            raise UseCaseError(Failure.NOT_TRANSCRIBED)
        template = await self._workspaces.default_template(found.workspace_id)
        context = await self._meetings.notes_context(meeting, MAX_CONTEXT_MEETINGS)
        sent = tuple(
            ContextReference(other.meeting.meeting_id, other.meeting.name) for other in context
        )
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
                    meeting_id=other.meeting.meeting_id,
                    name=other.meeting.name,
                    recorded_at=other.meeting.recorded_at,
                    transcript=_contract_transcript(other.transcript),
                )
                for other in context
            ),
            glossary=await self._glossary(found.workspace_id),
        ), sent

    async def _glossary(self, workspace_id: UUID) -> tuple[GlossaryEntry, ...]:
        return tuple(
            GlossaryEntry(
                term=item.term, preferred_form=item.preferred_form, description=item.description
            )
            for item in await self._meetings.workspace_glossary(workspace_id)
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


def _contract_transcript(version: TranscriptVersion) -> Transcript:
    names = {speaker.speaker_id: speaker.display_name for speaker in version.speakers}
    # Labels in order of first appearance, as the transcription contract lists them; members may
    # have given two speakers the same name, but the contract needs distinct labels.
    order = list(
        dict.fromkeys(
            segment.speaker_id for segment in version.segments if segment.speaker_id is not None
        )
    )
    order.extend(speaker_id for speaker_id in names if speaker_id not in order)
    labels: dict[UUID, str] = {}
    for speaker_id in order:
        label, copy = names[speaker_id], 2
        while label in labels.values():
            label, copy = f"{names[speaker_id]} ({copy})", copy + 1
        labels[speaker_id] = label
    return Transcript(
        language=version.transcript.language,
        speakers=tuple(labels.values()),
        segments=tuple(
            Segment(
                start_seconds=float(segment.start_time_seconds),
                end_seconds=float(segment.end_time_seconds),
                speaker=None if segment.speaker_id is None else labels[segment.speaker_id],
                text=segment.text,
            )
            for segment in version.segments
        ),
    )
