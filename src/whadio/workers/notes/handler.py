import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from ...contracts.notes import NotesFailed, NotesFailure, NotesReady, NotesRequested
from ..supervision.jobs import RunFailure
from .errors import NotesError
from .llm import IChatModel
from .output import parse_notes
from .prompt import PromptBuilder

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
        builder: PromptBuilder,
        model: IChatModel,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._builder: PromptBuilder = builder
        self._model: IChatModel = model
        self._now: Callable[[], datetime] = now

    async def handle(self, job: NotesRequested) -> NotesResult:
        try:
            prompt = self._builder.build(job)
            completion = await self._model.complete(prompt)
            notes = parse_notes(completion.text, prompt.headings)
        except NotesError as error:
            logger.warning("Notes for job %s failed: %s", job.job_id, error.reason)
            return NotesFailed(
                job_id=job.job_id,
                meeting_id=job.meeting_id,
                finished_at=self._now(),
                reason=error.reason,
            )
        logger.info(
            "Notes for job %s written by %s with %d context meetings",
            job.job_id,
            completion.model_name,
            len(prompt.context_meeting_ids),
        )
        return NotesReady(
            job_id=job.job_id,
            meeting_id=job.meeting_id,
            finished_at=self._now(),
            preset=job.preset,
            provider=self._model.provider,
            model_name=completion.model_name,
            content=notes.content,
            proposed_name=notes.proposed_name,
            context_meeting_ids=prompt.context_meeting_ids,
        )
