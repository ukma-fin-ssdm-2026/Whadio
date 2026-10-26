import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from functools import partial
from uuid import UUID, uuid4

import pytest

from conftest import NOW

from ..accounts.enums import LlmProvider, NotesTemplate
from ..contracts.common import JobKind, Segment, Transcript
from ..contracts.notes import (
    NotesFailed,
    NotesFailure,
    NotesPreset,
    NotesProvider,
    NotesReady,
    NotesRequested,
)
from ..contracts.results import JobStarted, ProcessingResult
from ..contracts.transcription import (
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
    TranscriptVersion,
)
from ..meetings.enums import ProcessingFailure, ProcessingState, RevisionType
from ..meetings.models import GlossaryTerm, Meeting, Speaker, TranscriptRevision, TranscriptSegment
from ..meetings.models import Transcript as StoredTranscript
from ..meetings.persistence import GeneratedNotes
from ..shared.errors import UseCaseError
from ..shared.fakes import FixedClock, InMemoryObjectStorage
from .enums import JobStatus, JobType
from .repositories import Job
from .services import (
    DEAD_LETTERED,
    MAX_ATTEMPTS,
    TRANSCRIPT_EXISTS,
    UNPUBLISHABLE,
    JobRequest,
    ProcessingCollaborators,
    ProcessingService,
)
from .speakers import SpeakerEvent


def stored_version(*speaker_names: str) -> TranscriptVersion:
    """One segment per speaker, in the order given."""
    transcript_id, revision_id = uuid4(), uuid4()
    speakers = [
        Speaker(speaker_id=uuid4(), revision_id=revision_id, display_name=name)
        for name in speaker_names or ("Speaker 1",)
    ]
    return TranscriptVersion(
        transcript=StoredTranscript(
            transcript_id=transcript_id,
            meeting_id=uuid4(),
            language="uk",
            model_name="parakeet",
            current_revision_id=revision_id,
        ),
        revision=TranscriptRevision(
            revision_id=revision_id,
            transcript_id=transcript_id,
            revision_type=RevisionType.ORIGINAL,
        ),
        original_revision_id=revision_id,
        is_edited=False,
        speakers=speakers,
        segments=[
            TranscriptSegment(
                segment_id=uuid4(),
                revision_id=revision_id,
                speaker_id=speaker.speaker_id,
                start_time_seconds=Decimal(index),
                end_time_seconds=Decimal(index + 1),
                text="Привіт",
            )
            for index, speaker in enumerate(speakers)
        ],
    )


def meeting_row(name: str = "Meeting 2026-10-11 12:00 UTC", *, generated: bool = True) -> Meeting:
    return Meeting(
        meeting_id=uuid4(),
        folder_id=uuid4(),
        name=name,
        name_is_generated=generated,
        storage_path="meetings/recording.mp4",
        recorded_at=NOW,
        processing_state=ProcessingState.QUEUED,
    )


class FakeJobs:
    def __init__(self) -> None:
        self.jobs: dict[UUID, Job] = {}
        self.published: set[UUID] = set()
        self.failure_reasons: dict[UUID, str | None] = {}

    async def add(self, meeting_id: UUID, job_type: JobType) -> UUID:
        job_id = uuid4()
        self.jobs[job_id] = Job(job_id, meeting_id, job_type, JobStatus.QUEUED, 0)
        return job_id

    async def lock(self, job_id: UUID) -> Job | None:
        return self.jobs.get(job_id)

    async def next_unpublished(self) -> Job | None:
        return next(
            (
                job
                for job in self.jobs.values()
                if job.status is JobStatus.QUEUED and job.job_id not in self.published
            ),
            None,
        )

    async def has_unfinished(self, meeting_id: UUID, job_type: JobType) -> bool:
        return any(
            job.meeting_id == meeting_id
            and job.job_type is job_type
            and job.status in (JobStatus.QUEUED, JobStatus.RUNNING)
            for job in self.jobs.values()
        )

    async def mark_published(
        self, job_id: UUID, _published_at: datetime, context: tuple[ContextReference, ...]
    ) -> None:
        self.published.add(job_id)
        self.jobs[job_id] = replace(self.jobs[job_id], sent_context=context)

    async def mark_running(self, job_id: UUID, _started_at: datetime) -> None:
        job = self.jobs[job_id]
        self.jobs[job_id] = replace(job, status=JobStatus.RUNNING, attempts=job.attempts + 1)

    async def requeue(self, job_id: UUID) -> None:
        self.published.discard(job_id)
        self.jobs[job_id] = replace(self.jobs[job_id], status=JobStatus.QUEUED)

    async def finish(
        self, job_id: UUID, status: JobStatus, _finished_at: datetime, failure_reason: str | None
    ) -> None:
        self.jobs[job_id] = replace(self.jobs[job_id], status=status)
        self.failure_reasons[job_id] = failure_reason


@dataclass
class FakeMeetings:
    meeting: Meeting
    workspace_id: UUID = field(default_factory=uuid4)
    update: ProcessingUpdate = field(
        default_factory=lambda: ProcessingUpdate(ProcessingState.QUEUED)
    )
    duration_seconds: int | None = None
    saved: InitialTranscript | None = None
    transcript: TranscriptVersion | None = None
    others: list[ContextTranscript] = field(default_factory=list[ContextTranscript])

    async def pipeline_meeting(
        self, meeting_id: UUID, *, lock: bool = False
    ) -> PipelineMeeting | None:
        del lock
        if meeting_id != self.meeting.meeting_id:
            return None
        return PipelineMeeting(self.meeting, self.workspace_id)

    async def current_transcript(self, _meeting_id: UUID) -> TranscriptVersion | None:
        return self.transcript

    async def notes_context(self, _meeting: Meeting, limit: int) -> list[ContextTranscript]:
        return self.others[:limit]

    async def workspace_glossary(self, workspace_id: UUID) -> list[GlossaryTerm]:
        return [
            GlossaryTerm(
                workspace_id=workspace_id,
                term="Whadio",
                preferred_form="Whadio",
                description="our product",
            )
        ]

    async def save_initial_transcript(
        self, _meeting_id: UUID, result: InitialTranscript, _now: datetime
    ) -> TranscriptVersion:
        self.saved = result
        self.transcript = stored_version(*(speaker.key for speaker in result.speakers))
        return self.transcript

    async def save_processing_state(self, _meeting_id: UUID, update: ProcessingUpdate) -> None:
        self.update = update
        self.duration_seconds = update.duration_seconds or self.duration_seconds


class FakeNotes:
    def __init__(self) -> None:
        self.saved: GeneratedNotes | None = None

    async def save_generated_notes(
        self, _meeting_id: UUID, notes: GeneratedNotes, _requester_id: UUID | None, _now: datetime
    ) -> None:
        self.saved = notes


class FakeWorkspaces:
    async def default_template(self, _workspace_id: UUID) -> NotesTemplate:
        return NotesTemplate.DETAILED


@dataclass
class FakeTimeline:
    events: tuple[SpeakerEvent, ...] = ()

    async def speaker_events(self, _meeting_id: UUID) -> tuple[SpeakerEvent, ...]:
        return self.events


class FakePublisher:
    def __init__(self) -> None:
        self.requests: list[JobRequest] = []
        self.unavailable: bool = False

    async def publish(self, request: JobRequest) -> None:
        if self.unavailable:
            raise ConnectionError
        self.requests.append(request)


@dataclass
class Pipeline:
    service: ProcessingService
    jobs: FakeJobs
    meetings: FakeMeetings
    notes: FakeNotes
    storage: InMemoryObjectStorage
    publisher: FakePublisher = field(default_factory=FakePublisher)

    @property
    def meeting_id(self) -> UUID:
        return self.meetings.meeting.meeting_id


def make_pipeline(
    meeting: Meeting | None = None, events: tuple[SpeakerEvent, ...] = ()
) -> Pipeline:
    jobs, meetings, notes = FakeJobs(), FakeMeetings(meeting or meeting_row()), FakeNotes()
    storage = InMemoryObjectStorage(now=FixedClock(NOW))
    return Pipeline(
        ProcessingService(
            ProcessingCollaborators(
                jobs, meetings, notes, FakeWorkspaces(), storage, FakeTimeline(events)
            )
        ),
        jobs,
        meetings,
        notes,
        storage,
    )


def add_job(
    pipeline: Pipeline,
    job_type: JobType,
    *,
    status: JobStatus = JobStatus.RUNNING,
    attempts: int = 1,
    sent: tuple[ContextReference, ...] = (),
) -> UUID:
    job_id = uuid4()
    pipeline.jobs.jobs[job_id] = Job(
        job_id, pipeline.meeting_id, job_type, status, attempts, sent_context=sent
    )
    pipeline.jobs.published.add(job_id)
    return job_id


def started(pipeline: Pipeline, job_id: UUID, kind: JobKind = JobKind.TRANSCRIPTION) -> JobStarted:
    return JobStarted(job_id=job_id, meeting_id=pipeline.meeting_id, kind=kind, started_at=NOW)


def transcription_failed(
    pipeline: Pipeline, job_id: UUID, reason: TranscriptionFailure
) -> TranscriptionFailed:
    return TranscriptionFailed(
        job_id=job_id, meeting_id=pipeline.meeting_id, finished_at=NOW, reason=reason
    )


def notes_failed(pipeline: Pipeline, job_id: UUID, reason: NotesFailure) -> NotesFailed:
    return NotesFailed(
        job_id=job_id, meeting_id=pipeline.meeting_id, finished_at=NOW, reason=reason
    )


def transcript_ready(pipeline: Pipeline, job_id: UUID) -> TranscriptReady:
    return TranscriptReady(
        job_id=job_id,
        meeting_id=pipeline.meeting_id,
        finished_at=NOW,
        model_name="parakeet",
        duration_seconds=61.6,
        transcript=Transcript(
            language="uk",
            speakers=("Speaker 1",),
            segments=(
                Segment(start_seconds=0.5, end_seconds=2.0, speaker="Speaker 1", text="Привіт"),
            ),
        ),
    )


def notes_ready(
    pipeline: Pipeline, job_id: UUID, context_meeting_ids: tuple[UUID, ...] = ()
) -> NotesReady:
    return NotesReady(
        job_id=job_id,
        meeting_id=pipeline.meeting_id,
        finished_at=NOW,
        preset=NotesPreset.DETAILED,
        provider=NotesProvider.ANTHROPIC,
        model_name="claude",
        content="## Summary",
        proposed_name="Sprint planning",
        context_meeting_ids=context_meeting_ids,
    )


def handle(pipeline: Pipeline, result: ProcessingResult) -> None:
    asyncio.run(pipeline.service.handle(result))


def queue(pipeline: Pipeline) -> None:
    asyncio.run(pipeline.service.queue_transcription(pipeline.meeting_id))


def publish_all(pipeline: Pipeline) -> list[JobRequest]:
    """Every request published so far, after publishing the jobs still waiting."""

    async def run() -> None:
        while await pipeline.service.publish_next(pipeline.publisher, NOW):
            pass

    asyncio.run(run())
    return pipeline.publisher.requests


def notes_requests(requests: list[JobRequest]) -> list[NotesRequested]:
    return [request for request in requests if isinstance(request, NotesRequested)]


def transcription_requests(requests: list[JobRequest]) -> list[TranscriptionRequested]:
    return [request for request in requests if isinstance(request, TranscriptionRequested)]


# --- Queueing ---


def test_queueing_records_a_queued_transcription_job() -> None:
    # Arrange
    pipeline = make_pipeline()
    # Act
    queue(pipeline)
    # Assert
    assert [(job.job_type, job.status) for job in pipeline.jobs.jobs.values()] == [
        (JobType.TRANSCRIPTION, JobStatus.QUEUED)
    ]


def test_queueing_publishes_nothing_by_itself() -> None:
    # Arrange
    pipeline = make_pipeline()
    # Act
    queue(pipeline)
    # Assert
    assert pipeline.publisher.requests == []


def test_queueing_an_unknown_meeting_is_refused() -> None:
    # Arrange
    pipeline = make_pipeline()
    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(pipeline.service.queue_transcription(uuid4()))
    # Assert
    assert failure.value.code == "NOT_FOUND"


def test_queueing_a_meeting_with_an_unfinished_transcription_is_refused() -> None:
    # Arrange
    pipeline = make_pipeline()
    add_job(pipeline, JobType.TRANSCRIPTION, status=JobStatus.QUEUED, attempts=0)
    # Act
    with pytest.raises(UseCaseError) as failure:
        queue(pipeline)
    # Assert
    assert failure.value.code == "ALREADY_PROCESSED"


def test_queueing_a_meeting_with_a_transcript_is_refused() -> None:
    # Arrange
    pipeline = make_pipeline()
    pipeline.meetings.transcript = stored_version()
    # Act
    with pytest.raises(UseCaseError) as failure:
        queue(pipeline)
    # Assert
    assert failure.value.code == "ALREADY_PROCESSED"


def test_notes_regeneration_is_unavailable() -> None:
    # Arrange
    pipeline = make_pipeline()
    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(
            pipeline.service.queue_notes(
                pipeline.meeting_id, uuid4(), None, use_builtin_model=True, now=NOW
            )
        )
    # Assert
    assert failure.value.code == "INTEGRATION_UNAVAILABLE"


# --- Publishing ---


def test_queued_transcription_is_published_with_a_presigned_link() -> None:
    # Arrange
    pipeline = make_pipeline()
    queue(pipeline)
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert [str(request.audio.url) for request in transcription_requests(requests)] == [
        "http://storage.test/recordings/meetings/recording.mp4"
    ]


def test_published_transcription_carries_the_workspace_glossary() -> None:
    # Arrange
    pipeline = make_pipeline()
    queue(pipeline)
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert [
        [entry.term for entry in request.glossary] for request in transcription_requests(requests)
    ] == [["Whadio"]]


def test_published_job_is_not_published_again() -> None:
    # Arrange
    pipeline = make_pipeline()
    queue(pipeline)
    publish_all(pipeline)
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert len(requests) == 1


def test_job_whose_publish_failed_is_published_on_the_next_round() -> None:
    # Arrange
    pipeline = make_pipeline()
    queue(pipeline)
    pipeline.publisher.unavailable = True
    with pytest.raises(ConnectionError):
        publish_all(pipeline)
    pipeline.publisher.unavailable = False
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert len(requests) == 1


def test_job_without_a_recording_fails_its_meeting_instead_of_publishing() -> None:
    # Arrange
    pipeline = make_pipeline()
    queue(pipeline)
    pipeline.meetings.meeting.storage_path = None
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert (requests, pipeline.meetings.update) == (
        [],
        ProcessingUpdate(ProcessingState.FAILED, ProcessingFailure.TRANSCRIPTION_FAILED),
    )


def test_job_without_a_recording_records_why_it_failed() -> None:
    # Arrange
    pipeline = make_pipeline()
    queue(pipeline)
    pipeline.meetings.meeting.storage_path = None
    # Act
    publish_all(pipeline)
    # Assert
    assert list(pipeline.jobs.failure_reasons.values()) == [UNPUBLISHABLE]


# --- Results ---


def test_started_job_marks_the_meeting_processing() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION, status=JobStatus.QUEUED, attempts=0)
    # Act
    handle(pipeline, started(pipeline, job_id))
    # Assert
    assert pipeline.meetings.update.state is ProcessingState.PROCESSING


def test_started_job_counts_an_attempt() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION, status=JobStatus.QUEUED, attempts=0)
    # Act
    handle(pipeline, started(pipeline, job_id))
    # Assert
    assert pipeline.jobs.jobs[job_id].attempts == 1


def test_late_start_of_a_running_job_counts_no_attempt() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION, attempts=1)
    # Act
    handle(pipeline, started(pipeline, job_id))
    # Assert
    assert pipeline.jobs.jobs[job_id].attempts == 1


def test_ready_transcript_is_saved_under_its_job() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    # Act
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Assert
    assert pipeline.meetings.saved == InitialTranscript(
        job_id=job_id,
        language="uk",
        model_name="parakeet",
        speakers=(InitialSpeaker("Speaker 1", "Speaker 1"),),
        segments=(InitialSegment("Speaker 1", Decimal("0.5"), Decimal("2.0"), "Привіт"),),
    )


def test_ready_transcript_names_the_speaker_the_capture_saw() -> None:
    # Arrange
    pipeline = make_pipeline(events=(SpeakerEvent(0.0, ("Alice",)),))
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    # Act
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Assert
    assert pipeline.meetings.saved is not None
    assert pipeline.meetings.saved.speakers == (InitialSpeaker("Speaker 1", "Alice"),)


def test_named_speaker_keeps_the_segments_on_its_label() -> None:
    # Arrange
    pipeline = make_pipeline(events=(SpeakerEvent(0.0, ("Alice",)),))
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    # Act
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Assert
    assert pipeline.meetings.saved is not None
    assert [segment.speaker_key for segment in pipeline.meetings.saved.segments] == ["Speaker 1"]


def test_ready_transcript_records_the_duration() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    # Act
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Assert
    assert pipeline.meetings.duration_seconds == 62


def test_transcript_of_a_second_job_is_not_saved() -> None:
    # Arrange
    pipeline = make_pipeline()
    pipeline.meetings.transcript = stored_version()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    # Act
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Assert
    assert (pipeline.meetings.saved, pipeline.jobs.failure_reasons[job_id]) == (
        None,
        TRANSCRIPT_EXISTS,
    )


def test_ready_transcript_queues_notes_with_the_workspace_preset() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert [request.preset for request in notes_requests(requests)] == [NotesPreset.DETAILED]


def test_notes_request_leaves_a_generated_name_out() -> None:
    # Arrange
    pipeline = make_pipeline(meeting_row(generated=True))
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert [request.meeting.name for request in notes_requests(requests)] == [None]


def test_notes_request_carries_a_name_a_member_gave() -> None:
    # Arrange
    pipeline = make_pipeline(meeting_row("Sprint review", generated=False))
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert [request.meeting.name for request in notes_requests(requests)] == ["Sprint review"]


def test_notes_request_carries_the_context_meetings() -> None:
    # Arrange
    pipeline = make_pipeline()
    other = meeting_row("Earlier sync")
    pipeline.meetings.others = [ContextTranscript(other, stored_version())]
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert [
        [context.meeting_id for context in request.context] for request in notes_requests(requests)
    ] == [[other.meeting_id]]


def test_published_notes_job_remembers_the_context_it_sent() -> None:
    # Arrange
    pipeline = make_pipeline()
    other = meeting_row("Earlier sync")
    pipeline.meetings.others = [ContextTranscript(other, stored_version())]
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Act
    publish_all(pipeline)
    # Assert
    assert [
        job.sent_context for job in pipeline.jobs.jobs.values() if job.job_type is JobType.NOTES
    ] == [(ContextReference(other.meeting_id, "Earlier sync"),)]


def test_notes_request_tells_apart_speakers_with_the_same_name() -> None:
    # Arrange
    pipeline = make_pipeline()
    pipeline.meetings.others = [
        ContextTranscript(meeting_row("Earlier sync"), stored_version("Anna", "Anna"))
    ]
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert [
        [context.transcript.speakers for context in request.context]
        for request in notes_requests(requests)
    ] == [[("Anna", "Anna (2)")]]


def test_ready_notes_are_saved_with_the_provider() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.NOTES)
    # Act
    handle(pipeline, notes_ready(pipeline, job_id))
    # Assert
    assert pipeline.notes.saved == GeneratedNotes(
        preset=NotesTemplate.DETAILED,
        provider=LlmProvider.ANTHROPIC,
        model_name="claude",
        content="## Summary",
        proposed_name="Sprint planning",
        context=(),
    )


def test_ready_notes_keep_only_context_meetings_that_were_sent() -> None:
    # Arrange
    pipeline = make_pipeline()
    sent = ContextReference(uuid4(), "Earlier sync")
    job_id = add_job(pipeline, JobType.NOTES, sent=(sent,))
    # Act
    handle(pipeline, notes_ready(pipeline, job_id, (uuid4(), sent.meeting_id)))
    # Assert
    assert (None if pipeline.notes.saved is None else pipeline.notes.saved.context) == (sent,)


def test_ready_notes_keep_the_context_names_as_sent() -> None:
    # Arrange
    pipeline = make_pipeline()
    renamed = meeting_row("Renamed since")
    pipeline.meetings.others = [ContextTranscript(renamed, stored_version())]
    sent = ContextReference(renamed.meeting_id, "Earlier sync")
    job_id = add_job(pipeline, JobType.NOTES, sent=(sent,))
    # Act
    handle(pipeline, notes_ready(pipeline, job_id, (sent.meeting_id,)))
    # Assert
    assert (None if pipeline.notes.saved is None else pipeline.notes.saved.context) == (sent,)


def test_ready_notes_save_a_repeated_context_meeting_once() -> None:
    # Arrange
    pipeline = make_pipeline()
    sent = ContextReference(uuid4(), "Earlier sync")
    job_id = add_job(pipeline, JobType.NOTES, sent=(sent,))
    # Act
    handle(pipeline, notes_ready(pipeline, job_id, (sent.meeting_id, sent.meeting_id)))
    # Assert
    assert (None if pipeline.notes.saved is None else len(pipeline.notes.saved.context)) == 1


def test_ready_notes_mark_the_meeting_processed() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.NOTES)
    # Act
    handle(pipeline, notes_ready(pipeline, job_id))
    # Assert
    assert pipeline.meetings.update.state is ProcessingState.PROCESSED


def test_duplicate_result_of_a_finished_job_queues_nothing_more() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Act
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Assert
    assert len(notes_requests(publish_all(pipeline))) == 1


def test_result_of_an_unknown_job_is_ignored() -> None:
    # Arrange
    pipeline = make_pipeline()
    # Act
    handle(pipeline, transcript_ready(pipeline, uuid4()))
    # Assert
    assert (pipeline.jobs.jobs, pipeline.meetings.saved) == ({}, None)


def test_result_of_another_meeting_changes_nothing() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    result = transcript_ready(pipeline, job_id).model_copy(update={"meeting_id": uuid4()})
    # Act
    handle(pipeline, result)
    # Assert
    assert pipeline.meetings.saved is None


def test_notes_for_a_transcription_job_change_nothing() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    # Act
    handle(pipeline, notes_ready(pipeline, job_id))
    # Assert
    assert pipeline.meetings.update.state is ProcessingState.QUEUED


def test_transcript_for_a_notes_job_changes_nothing() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.NOTES)
    # Act
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Assert
    assert (len(pipeline.jobs.jobs), pipeline.meetings.saved) == (1, None)


def test_start_of_another_kind_of_job_changes_nothing() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION, status=JobStatus.QUEUED, attempts=0)
    # Act
    handle(pipeline, started(pipeline, job_id, JobKind.NOTES))
    # Assert
    assert pipeline.jobs.jobs[job_id].status is JobStatus.QUEUED


# --- Failures ---


def test_retryable_failure_publishes_the_same_job_again() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    handle(
        pipeline, transcription_failed(pipeline, job_id, TranscriptionFailure.AUDIO_LINK_EXPIRED)
    )
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert [(type(request), request.job_id) for request in requests] == [
        (TranscriptionRequested, job_id)
    ]


def test_redelivered_failure_of_a_requeued_job_publishes_nothing_more() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    failed = transcription_failed(pipeline, job_id, TranscriptionFailure.AUDIO_LINK_EXPIRED)
    handle(pipeline, failed)
    # Act
    handle(pipeline, failed)
    # Assert
    assert len(publish_all(pipeline)) == 1


def test_retryable_failure_one_attempt_before_the_limit_publishes_the_job_again() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION, attempts=MAX_ATTEMPTS - 1)
    handle(
        pipeline, transcription_failed(pipeline, job_id, TranscriptionFailure.AUDIO_LINK_EXPIRED)
    )
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert [request.job_id for request in requests] == [job_id]


def test_job_at_the_attempt_limit_is_not_published_again() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION, attempts=MAX_ATTEMPTS)
    handle(
        pipeline, transcription_failed(pipeline, job_id, TranscriptionFailure.AUDIO_LINK_EXPIRED)
    )
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert requests == []


def test_job_above_the_attempt_limit_is_not_published_again() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION, attempts=MAX_ATTEMPTS + 1)
    handle(
        pipeline, transcription_failed(pipeline, job_id, TranscriptionFailure.AUDIO_LINK_EXPIRED)
    )
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert requests == []


def test_retryable_failure_past_the_attempt_limit_fails_the_meeting() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.NOTES, attempts=MAX_ATTEMPTS)
    # Act
    handle(pipeline, notes_failed(pipeline, job_id, NotesFailure.PROVIDER_UNAVAILABLE))
    # Assert
    assert pipeline.meetings.update == ProcessingUpdate(
        ProcessingState.FAILED, ProcessingFailure.PROVIDER_UNAVAILABLE
    )


def test_permanent_failure_records_its_reason_on_the_job() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    failed = transcription_failed(pipeline, job_id, TranscriptionFailure.UNSUPPORTED_AUDIO)
    # Act
    handle(pipeline, failed)
    # Assert
    assert pipeline.jobs.failure_reasons[job_id] == "unsupported_audio"


@pytest.mark.parametrize(
    ("reason", "shown"),
    [
        (TranscriptionFailure.UNSUPPORTED_AUDIO, ProcessingFailure.TRANSCRIPTION_FAILED),
        (TranscriptionFailure.TIMED_OUT, ProcessingFailure.PROCESSING_TIMEOUT),
    ],
)
def test_failed_transcription_shows_why_on_the_meeting(
    reason: TranscriptionFailure, shown: ProcessingFailure
) -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    # Act
    handle(pipeline, transcription_failed(pipeline, job_id, reason))
    # Assert
    assert pipeline.meetings.update.failure is shown


@pytest.mark.parametrize(
    ("reason", "shown"),
    [
        (NotesFailure.TRANSCRIPT_TOO_LONG, ProcessingFailure.NOTES_FAILED),
        (NotesFailure.PROVIDER_AUTH_FAILED, ProcessingFailure.PROVIDER_REJECTED),
        (NotesFailure.PROVIDER_REFUSED, ProcessingFailure.PROVIDER_REJECTED),
    ],
)
def test_failed_notes_show_why_on_the_meeting(
    reason: NotesFailure, shown: ProcessingFailure
) -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.NOTES)
    # Act
    handle(pipeline, notes_failed(pipeline, job_id, reason))
    # Assert
    assert pipeline.meetings.update.failure is shown


# --- Dead letters ---


def test_dead_lettered_job_fails_its_meeting() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION, status=JobStatus.QUEUED)
    # Act
    asyncio.run(pipeline.service.dead_lettered(job_id, NOW))
    # Assert
    assert pipeline.meetings.update == ProcessingUpdate(
        ProcessingState.FAILED, ProcessingFailure.TRANSCRIPTION_FAILED
    )


def test_dead_lettered_job_records_why_it_failed() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.NOTES)
    # Act
    asyncio.run(pipeline.service.dead_lettered(job_id, NOW))
    # Assert
    assert pipeline.jobs.failure_reasons[job_id] == DEAD_LETTERED


def test_dead_letter_of_a_finished_job_changes_nothing() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.NOTES, status=JobStatus.SUCCEEDED)
    # Act
    asyncio.run(pipeline.service.dead_lettered(job_id, NOW))
    # Assert
    assert pipeline.meetings.update.state is ProcessingState.QUEUED


# --- Recording storage ---


@pytest.mark.parametrize(
    "finish",
    [notes_ready, partial(notes_failed, reason=NotesFailure.PROVIDER_AUTH_FAILED)],
    ids=["processed", "failed"],
)
def test_processing_a_meeting_neither_uploads_nor_deletes_its_recording(
    finish: Callable[[Pipeline, UUID], ProcessingResult],
) -> None:
    # Arrange
    pipeline = make_pipeline()
    # Act
    queue(pipeline)
    (transcription,) = transcription_requests(publish_all(pipeline))
    handle(pipeline, started(pipeline, transcription.job_id))
    handle(pipeline, transcript_ready(pipeline, transcription.job_id))
    (notes,) = notes_requests(publish_all(pipeline))
    handle(pipeline, started(pipeline, notes.job_id, JobKind.NOTES))
    handle(pipeline, finish(pipeline, notes.job_id))
    # Assert
    assert (pipeline.storage.uploaded, pipeline.storage.deleted) == ([], [])
