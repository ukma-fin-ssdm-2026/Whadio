from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import AsyncDatabase

from ...contracts.common import JobKind, Segment, Transcript
from ...contracts.notes import NotesPreset, NotesProvider, NotesReady, NotesRequested
from ...contracts.results import JobStarted, ProcessingResult
from ...contracts.transcription import TranscriptionFailed, TranscriptionFailure, TranscriptReady
from ...meetings.contracts import ProcessingUpdate
from ...meetings.enums import ProcessingFailure, ProcessingState
from ...shared.fakes import FixedClock, InMemoryObjectStorage
from ..enums import ProcessingOutcome
from ..recovery import JobRecovery
from ..repositories import JobRepository
from ..services import (
    MAX_ATTEMPTS,
    JobRequest,
    ProcessingCollaborators,
    ProcessingNotice,
    ProcessingService,
)
from ..settings import JobRecoverySettings
from ..test_repositories import only_new_jobs_unpublished
from ..test_services import (
    FakeMeetings,
    FakeNotes,
    FakeNotices,
    FakeReaders,
    FakeTimeline,
    FakeWorkspaces,
    meeting_row,
)

LIMITS: Final = JobRecoverySettings()
QUEUED_AT: Final = datetime(1991, 5, 1, tzinfo=UTC)
TICK: Final = timedelta(microseconds=1)


class LosingBroker:
    """Accepts every job and delivers none, as a purged queue or a recreated broker volume does."""

    def __init__(self) -> None:
        self.requests: list[JobRequest] = []

    async def publish(self, request: JobRequest) -> None:
        self.requests.append(request)


@dataclass
class Processing:
    """Processing over the real job table, with doubles for everything around it."""

    service: ProcessingService
    recovery: JobRecovery
    broker: LosingBroker
    meetings: FakeMeetings
    notices: FakeNotices

    async def publish(self, now: datetime) -> None:
        while await self.service.publish_next(self.broker, now):
            pass

    async def recover(self, now: datetime) -> None:
        await self.recovery.recover(now)
        await self.publish(now)


async def deliver(service: ProcessingService, result: ProcessingResult) -> None:
    await service.handle(result, uuid4())


async def processing_with_a_queued_meeting(session: AsyncSession) -> Processing:
    await only_new_jobs_unpublished(session)
    meeting = meeting_row()
    meeting.meeting_id = await AsyncDatabase.add_meeting(
        session, await AsyncDatabase.add_workspace(session)
    )
    jobs, meetings, notices = JobRepository(session), FakeMeetings(meeting), FakeNotices()
    service = ProcessingService(
        ProcessingCollaborators(
            jobs,
            meetings,
            FakeNotes(),
            FakeWorkspaces(),
            InMemoryObjectStorage(now=FixedClock(QUEUED_AT)),
            FakeTimeline(),
            notices,
            FakeReaders(),
        )
    )
    await service.queue_transcription(meeting.meeting_id)
    return Processing(service, JobRecovery(jobs, LIMITS), LosingBroker(), meetings, notices)


async def start_last(processing: Processing, started_at: datetime) -> None:
    """A worker takes the last job published and reports it started."""
    request = processing.broker.requests[-1]
    kind = JobKind.NOTES if isinstance(request, NotesRequested) else JobKind.TRANSCRIPTION
    await deliver(
        processing.service,
        JobStarted(
            job_id=request.job_id, meeting_id=request.meeting_id, kind=kind, started_at=started_at
        ),
    )


async def answer_last(processing: Processing, finished_at: datetime) -> None:
    """The worker of the last job published sends its successful result."""
    request = processing.broker.requests[-1]
    job_id, meeting_id = request.job_id, request.meeting_id
    if isinstance(request, NotesRequested):
        await deliver(
            processing.service,
            NotesReady(
                job_id=job_id,
                meeting_id=meeting_id,
                finished_at=finished_at,
                preset=NotesPreset.DETAILED,
                provider=NotesProvider.ANTHROPIC,
                model_name="claude",
                content="## Summary",
                proposed_name="Planning",
                context_meeting_ids=(),
            ),
        )
        return
    segment = Segment(start_seconds=0.0, end_seconds=1.0, speaker="Speaker 1", text="Привіт")
    await deliver(
        processing.service,
        TranscriptReady(
            job_id=job_id,
            meeting_id=meeting_id,
            finished_at=finished_at,
            model_name="parakeet",
            duration_seconds=1.0,
            transcript=Transcript(language="uk", speakers=("Speaker 1",), segments=(segment,)),
        ),
    )


@pytest.mark.slow
def test_job_whose_message_was_lost_is_published_again_after_the_unstarted_limit(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[int, int]:
        processing = await processing_with_a_queued_meeting(session)
        await processing.publish(QUEUED_AT)
        # Act
        await processing.recover(QUEUED_AT + LIMITS.unstarted_limit + TICK)
        requests = processing.broker.requests
        return len(requests), len({request.job_id for request in requests})

    publishes, jobs = async_database.run(scenario)
    # Assert
    assert (publishes, jobs) == (2, 1)


@pytest.mark.slow
def test_job_lost_on_every_publish_fails_its_meeting_with_one_notice_after_its_attempts(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> tuple[ProcessingUpdate, list[ProcessingNotice]]:
        processing = await processing_with_a_queued_meeting(session)
        now = QUEUED_AT
        await processing.publish(now)
        # Act
        for _ in range(MAX_ATTEMPTS):
            now += LIMITS.unstarted_limit + TICK
            await processing.recover(now)
        return processing.meetings.update, processing.notices.sent

    update, notices = async_database.run(scenario)
    # Assert
    assert (update, [notice.outcome for notice in notices]) == (
        ProcessingUpdate(ProcessingState.FAILED, ProcessingFailure.PROCESSING_TIMEOUT),
        [ProcessingOutcome.FAILED],
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    ("past_the_limit", "publishes"),
    [
        pytest.param(timedelta(0), 1, id="bva-on-limit"),
        pytest.param(TICK, 2, id="bva-above-limit"),
    ],
)
def test_job_whose_result_was_lost_is_published_again_only_once_past_its_running_limit(
    async_database: AsyncDatabase, past_the_limit: timedelta, publishes: int
) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> int:
        processing = await processing_with_a_queued_meeting(session)
        await processing.publish(QUEUED_AT)
        await start_last(processing, QUEUED_AT)
        # Act
        await processing.recover(QUEUED_AT + LIMITS.transcription_running_limit + past_the_limit)
        return len(processing.broker.requests)

    found = async_database.run(scenario)
    # Assert
    assert found == publishes


@pytest.mark.slow
def test_late_failure_of_a_handed_back_attempt_leaves_its_replacement_to_finish(
    async_database: AsyncDatabase,
) -> None:
    # Arrange
    second_start = QUEUED_AT + LIMITS.transcription_running_limit + TICK

    async def scenario(
        session: AsyncSession,
    ) -> tuple[bool, ProcessingState, list[ProcessingOutcome]]:
        processing = await processing_with_a_queued_meeting(session)
        await processing.publish(QUEUED_AT)
        await start_last(processing, QUEUED_AT)
        first = processing.broker.requests[-1]
        await processing.recover(second_start)
        await start_last(processing, second_start)
        late_failure = TranscriptionFailed(
            job_id=first.job_id,
            meeting_id=first.meeting_id,
            finished_at=QUEUED_AT + timedelta(hours=2),
            reason=TranscriptionFailure.TIMED_OUT,
        )
        # Act
        await deliver(processing.service, late_failure)
        await answer_last(processing, second_start + timedelta(minutes=1))
        await processing.publish(second_start + timedelta(minutes=1))
        await start_last(processing, second_start + timedelta(minutes=2))
        await answer_last(processing, second_start + timedelta(minutes=3))
        meetings = processing.meetings
        outcomes = [notice.outcome for notice in processing.notices.sent]
        return meetings.saved is not None, meetings.update.state, outcomes

    found = async_database.run(scenario)
    # Assert
    assert found == (True, ProcessingState.PROCESSED, [ProcessingOutcome.FINISHED])
