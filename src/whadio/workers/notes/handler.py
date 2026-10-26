import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from ...contracts.notes import NotesFailed, NotesFailure, NotesReady, NotesRequested
from ..supervision.jobs import RunFailure
from .errors import NotesError
from .writer import NotesWriter

logger = logging.getLogger(__name__)

type NotesResult = NotesReady | NotesFailed

_RUN_FAILURES: Final = {
    RunFailure.CRASHED: NotesFailure.INTERNAL_ERROR,
    RunFailure.TIMED_OUT: NotesFailure.TIMED_OUT,
    RunFailure.ERRORED: NotesFailure.INTERNAL_ERROR,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def notes_failure(job: NotesRequested, failure: RunFailure) -> NotesResult:
    return NotesFailed(
        job_id=job.job_id,
        meeting_id=job.meeting_id,
        finished_at=_utc_now(),
        reason=_RUN_FAILURES[failure],
    )


class NotesHandler:
    def __init__(
        self,
        writer: NotesWriter,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._writer: NotesWriter = writer
        self._now: Callable[[], datetime] = now

    async def handle(self, job: NotesRequested) -> NotesResult:
        try:
            written = await self._writer.write(job)
        except NotesError as error:
            logger.warning("Notes for job %s failed: %s", job.job_id, error.reason)
            return NotesFailed(
                job_id=job.job_id,
                meeting_id=job.meeting_id,
                finished_at=self._now(),
                reason=error.reason,
            )
        logger.info(
            "Notes for job %s written by %s from %d transcript parts with %d context meetings",
            job.job_id,
            written.model_name,
            written.transcript_parts,
            len(written.context_meeting_ids),
        )
        return NotesReady(
            job_id=job.job_id,
            meeting_id=job.meeting_id,
            finished_at=self._now(),
            preset=job.preset,
            provider=written.provider,
            model_name=written.model_name,
            content=written.notes.content,
            proposed_name=written.notes.proposed_name,
            context_meeting_ids=written.context_meeting_ids,
        )
