import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import BinaryIO
from uuid import UUID, uuid4

import pytest

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
from ..meetings.enums import ProcessingState
from ..meetings.repositories import (
    ContextCandidate,
    GeneratedNotes,
    GlossaryItem,
    MeetingSummary,
    PipelineMeeting,
    StoredTranscript,
    TranscriptLine,
)
from ..shared.errors import UseCaseError
from ..shared.storage import PresignedUrl
from .enums import JobStatus, JobType
from .repositories import Job
from .services import DEAD_LETTERED, MAX_ATTEMPTS, JobRequest, ProcessingService

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
STORED = StoredTranscript(
    language="uk",
    speakers=("Speaker 1",),
    lines=(TranscriptLine(Decimal("0.5"), Decimal("2.0"), "Speaker 1", "Привіт"),),
)


class FakeJobs:
    def __init__(self) -> None:
        self.jobs: dict[UUID, Job] = {}
        self.failure_reasons: dict[UUID, str | None] = {}

    async def add(self, meeting_id: UUID, job_type: JobType) -> UUID:
        job_id = uuid4()
        self.jobs[job_id] = Job(job_id, meeting_id, job_type, JobStatus.QUEUED, 0)
        return job_id

    async def lock(self, job_id: UUID) -> Job | None:
        return self.jobs.get(job_id)

    async def has_unfinished(self, meeting_id: UUID, job_type: JobType) -> bool:
        return any(
            job.meeting_id == meeting_id
            and job.job_type is job_type
            and job.status in (JobStatus.QUEUED, JobStatus.RUNNING)
            for job in self.jobs.values()
        )

    async def mark_running(self, job_id: UUID, _started_at: datetime) -> None:
        job = self.jobs[job_id]
        self.jobs[job_id] = replace(job, status=JobStatus.RUNNING, attempts=job.attempts + 1)

    async def requeue(self, job_id: UUID) -> None:
        self.jobs[job_id] = replace(self.jobs[job_id], status=JobStatus.QUEUED)

    async def finish(
        self, job_id: UUID, status: JobStatus, _finished_at: datetime, failure_reason: str | None
    ) -> None:
        self.jobs[job_id] = replace(self.jobs[job_id], status=status)
        self.failure_reasons[job_id] = failure_reason


@dataclass
class FakeMeetings:
    meeting_record: PipelineMeeting
    state: ProcessingState = ProcessingState.QUEUED
    stored: StoredTranscript | None = None
    notes: GeneratedNotes | None = None
    others: list[ContextCandidate] = field(default_factory=list[ContextCandidate])

    async def meeting(self, meeting_id: UUID) -> PipelineMeeting | None:
        return self.meeting_record if meeting_id == self.meeting_record.meeting_id else None

    async def lock(self, meeting_id: UUID) -> PipelineMeeting | None:
        return await self.meeting(meeting_id)

    async def has_transcript(self, _meeting_id: UUID) -> bool:
        return self.stored is not None

    async def set_state(self, _meeting_id: UUID, state: ProcessingState) -> None:
        self.state = state

    async def save_original_transcript(
        self,
        _meeting_id: UUID,
        _model_name: str,
        _duration_seconds: int,
        transcript: StoredTranscript,
    ) -> None:
        self.stored = transcript

    async def transcript(self, _meeting_id: UUID) -> StoredTranscript | None:
        return self.stored

    async def context_summaries(
        self, _meeting: PipelineMeeting, limit: int
    ) -> list[MeetingSummary]:
        return [
            MeetingSummary(other.meeting_id, other.name, other.recorded_at)
            for other in self.others[:limit]
        ]

    async def context(self, _meeting: PipelineMeeting, limit: int) -> list[ContextCandidate]:
        return self.others[:limit]

    async def glossary(self, _workspace_id: UUID) -> list[GlossaryItem]:
        return [GlossaryItem("Whadio", "Whadio", "our product")]

    async def save_notes(self, _meeting: PipelineMeeting, notes: GeneratedNotes) -> None:
        self.notes = notes


class FakeWorkspaces:
    async def default_template(self, _workspace_id: UUID) -> NotesTemplate:
        return NotesTemplate.DETAILED


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: BinaryIO, *, content_type: str) -> None:
        self.objects[key] = (data.read(), content_type)

    def delete(self, key: str) -> None:
        del self.objects[key]

    def presign_get(self, key: str, *, expires_in: timedelta) -> PresignedUrl:
        return PresignedUrl(
            url=f"http://storage.test/recordings/{key}", expires_at=NOW + expires_in
        )


@dataclass
class Pipeline:
    service: ProcessingService
    jobs: FakeJobs
    meetings: FakeMeetings


def make_pipeline(*, name_is_generated: bool = True) -> Pipeline:
    jobs = FakeJobs()
    meetings = FakeMeetings(
        PipelineMeeting(
            meeting_id=uuid4(),
            workspace_id=uuid4(),
            folder_id=uuid4(),
            storage_path="meetings/recording.mp4",
            name="Meeting 2026-10-11 12:00 UTC",
            name_is_generated=name_is_generated,
            recorded_at=NOW,
        )
    )
    return Pipeline(
        ProcessingService(jobs, meetings, FakeWorkspaces(), FakeStorage(), now=lambda: NOW),
        jobs,
        meetings,
    )


def add_job(
    pipeline: Pipeline,
    job_type: JobType,
    *,
    status: JobStatus = JobStatus.RUNNING,
    attempts: int = 1,
) -> UUID:
    job_id = uuid4()
    pipeline.jobs.jobs[job_id] = Job(
        job_id, pipeline.meetings.meeting_record.meeting_id, job_type, status, attempts
    )
    return job_id


def started(pipeline: Pipeline, job_id: UUID, kind: JobKind = JobKind.TRANSCRIPTION) -> JobStarted:
    return JobStarted(
        job_id=job_id,
        meeting_id=pipeline.meetings.meeting_record.meeting_id,
        kind=kind,
        started_at=NOW,
    )


def transcription_failed(
    pipeline: Pipeline, job_id: UUID, reason: TranscriptionFailure
) -> TranscriptionFailed:
    return TranscriptionFailed(
        job_id=job_id,
        meeting_id=pipeline.meetings.meeting_record.meeting_id,
        finished_at=NOW,
        reason=reason,
    )


def transcript_ready(pipeline: Pipeline, job_id: UUID) -> TranscriptReady:
    return TranscriptReady(
        job_id=job_id,
        meeting_id=pipeline.meetings.meeting_record.meeting_id,
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
        meeting_id=pipeline.meetings.meeting_record.meeting_id,
        finished_at=NOW,
        preset=NotesPreset.DETAILED,
        provider=NotesProvider.ANTHROPIC,
        model_name="claude",
        content="## Summary",
        proposed_name="Sprint planning",
        context_meeting_ids=context_meeting_ids,
    )


def handle(pipeline: Pipeline, result: ProcessingResult) -> list[JobRequest]:
    return asyncio.run(pipeline.service.handle(result))


# --- Queueing ---


def test_queueing_publishes_a_presigned_link_to_the_recording() -> None:
    # Arrange
    pipeline = make_pipeline()
    # Act
    request = asyncio.run(
        pipeline.service.queue_transcription(pipeline.meetings.meeting_record.meeting_id)
    )
    # Assert
    assert str(request.audio.url) == "http://storage.test/recordings/meetings/recording.mp4"


def test_queueing_records_a_queued_transcription_job() -> None:
    # Arrange
    pipeline = make_pipeline()
    # Act
    request = asyncio.run(
        pipeline.service.queue_transcription(pipeline.meetings.meeting_record.meeting_id)
    )
    # Assert
    assert (
        pipeline.jobs.jobs[request.job_id].job_type,
        pipeline.jobs.jobs[request.job_id].status,
    ) == (
        JobType.TRANSCRIPTION,
        JobStatus.QUEUED,
    )


def test_queueing_passes_the_workspace_glossary() -> None:
    # Arrange
    pipeline = make_pipeline()
    # Act
    request = asyncio.run(
        pipeline.service.queue_transcription(pipeline.meetings.meeting_record.meeting_id)
    )
    # Assert
    assert [entry.term for entry in request.glossary] == ["Whadio"]


def test_queueing_an_unknown_meeting_is_refused() -> None:
    # Arrange
    pipeline = make_pipeline()
    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(pipeline.service.queue_transcription(uuid4()))
    # Assert
    assert failure.value.code == "NOT_FOUND"


def test_queueing_without_a_recording_is_refused() -> None:
    # Arrange
    pipeline = make_pipeline()
    pipeline.meetings.meeting_record = replace(pipeline.meetings.meeting_record, storage_path=None)
    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(
            pipeline.service.queue_transcription(pipeline.meetings.meeting_record.meeting_id)
        )
    # Assert
    assert failure.value.code == "NOT_FOUND"


def test_queueing_a_meeting_with_an_unfinished_transcription_is_refused() -> None:
    # Arrange
    pipeline = make_pipeline()
    add_job(pipeline, JobType.TRANSCRIPTION, status=JobStatus.QUEUED, attempts=0)
    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(
            pipeline.service.queue_transcription(pipeline.meetings.meeting_record.meeting_id)
        )
    # Assert
    assert failure.value.code == "ALREADY_PROCESSED"


def test_queueing_a_meeting_with_a_transcript_is_refused() -> None:
    # Arrange
    pipeline = make_pipeline()
    pipeline.meetings.stored = STORED
    # Act
    with pytest.raises(UseCaseError) as failure:
        asyncio.run(
            pipeline.service.queue_transcription(pipeline.meetings.meeting_record.meeting_id)
        )
    # Assert
    assert failure.value.code == "ALREADY_PROCESSED"


# --- Results ---


def test_started_job_marks_the_meeting_processing() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION, status=JobStatus.QUEUED, attempts=0)
    # Act
    handle(pipeline, started(pipeline, job_id))
    # Assert
    assert pipeline.meetings.state is ProcessingState.PROCESSING


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


def test_ready_transcript_is_saved() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    # Act
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Assert
    assert pipeline.meetings.stored == STORED


def test_ready_transcript_queues_notes_with_the_workspace_preset() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    # Act
    requests = handle(pipeline, transcript_ready(pipeline, job_id))
    # Assert
    assert [r.preset for r in requests if isinstance(r, NotesRequested)] == [NotesPreset.DETAILED]


def test_notes_request_leaves_a_generated_name_out() -> None:
    # Arrange
    pipeline = make_pipeline(name_is_generated=True)
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    # Act
    requests = handle(pipeline, transcript_ready(pipeline, job_id))
    # Assert
    assert [r.meeting.name for r in requests if isinstance(r, NotesRequested)] == [None]


def test_notes_request_carries_the_context_meetings() -> None:
    # Arrange
    pipeline = make_pipeline()
    other = ContextCandidate(uuid4(), "Earlier sync", NOW - timedelta(days=1), STORED)
    pipeline.meetings.others = [other]
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    # Act
    requests = handle(pipeline, transcript_ready(pipeline, job_id))
    # Assert
    assert [
        [context.meeting_id for context in r.context]
        for r in requests
        if isinstance(r, NotesRequested)
    ] == [[other.meeting_id]]


def test_ready_notes_are_saved_with_the_provider() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.NOTES)
    # Act
    handle(pipeline, notes_ready(pipeline, job_id))
    # Assert
    assert pipeline.meetings.notes == GeneratedNotes(
        template=NotesTemplate.DETAILED,
        provider=LlmProvider.ANTHROPIC,
        model_name="claude",
        content="## Summary",
        proposed_name="Sprint planning",
        context=(),
    )


def test_ready_notes_keep_only_context_meetings_that_were_sent() -> None:
    # Arrange
    pipeline = make_pipeline()
    sent = ContextCandidate(uuid4(), "Earlier sync", NOW - timedelta(days=1), STORED)
    pipeline.meetings.others = [sent]
    job_id = add_job(pipeline, JobType.NOTES)
    # Act
    handle(pipeline, notes_ready(pipeline, job_id, (uuid4(), sent.meeting_id)))
    # Assert
    assert (None if pipeline.meetings.notes is None else pipeline.meetings.notes.context) == (
        MeetingSummary(sent.meeting_id, sent.name, sent.recorded_at),
    )


def test_ready_notes_save_a_repeated_context_meeting_once() -> None:
    # Arrange
    pipeline = make_pipeline()
    sent = ContextCandidate(uuid4(), "Earlier sync", NOW - timedelta(days=1), STORED)
    pipeline.meetings.others = [sent]
    job_id = add_job(pipeline, JobType.NOTES)
    # Act
    handle(pipeline, notes_ready(pipeline, job_id, (sent.meeting_id, sent.meeting_id)))
    # Assert
    assert (None if pipeline.meetings.notes is None else len(pipeline.meetings.notes.context)) == 1


def test_ready_notes_mark_the_meeting_processed() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.NOTES)
    # Act
    handle(pipeline, notes_ready(pipeline, job_id))
    # Assert
    assert pipeline.meetings.state is ProcessingState.PROCESSED


def test_duplicate_result_of_a_finished_job_is_ignored() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    handle(pipeline, transcript_ready(pipeline, job_id))
    # Act
    requests = handle(pipeline, transcript_ready(pipeline, job_id))
    # Assert
    assert requests == []


def test_result_of_an_unknown_job_is_ignored() -> None:
    # Arrange
    pipeline = make_pipeline()
    # Act
    requests = handle(pipeline, transcript_ready(pipeline, uuid4()))
    # Assert
    assert requests == []


def test_result_of_another_meeting_changes_nothing() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    result = transcript_ready(pipeline, job_id).model_copy(update={"meeting_id": uuid4()})
    # Act
    handle(pipeline, result)
    # Assert
    assert pipeline.meetings.stored is None


def test_notes_for_a_transcription_job_change_nothing() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    # Act
    handle(pipeline, notes_ready(pipeline, job_id))
    # Assert
    assert pipeline.meetings.state is ProcessingState.QUEUED


def test_transcript_for_a_notes_job_changes_nothing() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.NOTES)
    # Act
    requests = handle(pipeline, transcript_ready(pipeline, job_id))
    # Assert
    assert (requests, pipeline.meetings.stored) == ([], None)


def test_start_of_another_kind_of_job_changes_nothing() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION, status=JobStatus.QUEUED, attempts=0)
    # Act
    handle(pipeline, started(pipeline, job_id, JobKind.NOTES))
    # Assert
    assert pipeline.jobs.jobs[job_id].status is JobStatus.QUEUED


def test_retryable_failure_publishes_the_same_job_again() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    failed = transcription_failed(pipeline, job_id, TranscriptionFailure.AUDIO_LINK_EXPIRED)
    # Act
    requests = handle(pipeline, failed)
    # Assert
    assert [(type(request), request.job_id) for request in requests] == [
        (TranscriptionRequested, job_id)
    ]


def test_redelivered_failure_of_a_requeued_job_publishes_nothing() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    failed = transcription_failed(pipeline, job_id, TranscriptionFailure.AUDIO_LINK_EXPIRED)
    handle(pipeline, failed)
    # Act
    requests = handle(pipeline, failed)
    # Assert
    assert requests == []


def test_retryable_failure_past_the_attempt_limit_fails_the_meeting() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.NOTES, attempts=MAX_ATTEMPTS)
    failed = NotesFailed(
        job_id=job_id,
        meeting_id=pipeline.meetings.meeting_record.meeting_id,
        finished_at=NOW,
        reason=NotesFailure.PROVIDER_UNAVAILABLE,
    )
    # Act
    handle(pipeline, failed)
    # Assert
    assert pipeline.meetings.state is ProcessingState.FAILED


def test_permanent_failure_records_its_reason() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION)
    failed = transcription_failed(pipeline, job_id, TranscriptionFailure.UNSUPPORTED_AUDIO)
    # Act
    handle(pipeline, failed)
    # Assert
    assert pipeline.jobs.failure_reasons[job_id] == "unsupported_audio"


# --- Dead letters ---


def test_dead_lettered_job_fails_its_meeting() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION, status=JobStatus.QUEUED)
    # Act
    asyncio.run(pipeline.service.dead_lettered(job_id))
    # Assert
    assert pipeline.meetings.state is ProcessingState.FAILED


def test_dead_lettered_job_records_why_it_failed() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.NOTES)
    # Act
    asyncio.run(pipeline.service.dead_lettered(job_id))
    # Assert
    assert pipeline.jobs.failure_reasons[job_id] == DEAD_LETTERED


def test_dead_letter_of_a_finished_job_changes_nothing() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.NOTES, status=JobStatus.SUCCEEDED)
    # Act
    asyncio.run(pipeline.service.dead_lettered(job_id))
    # Assert
    assert pipeline.meetings.state is ProcessingState.QUEUED
