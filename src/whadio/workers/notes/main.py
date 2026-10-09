import asyncio
import signal
from datetime import timedelta
from typing import Final

import anthropic

from ...contracts.common import JobKind
from ...contracts.notes import NotesRequested
from ...contracts.queues import NOTES_REQUESTS
from ...shared.logs import configure_logging
from ..supervision.jobs import WorkerSpec
from ..supervision.runners import InlineRunner
from ..supervision.supervisor import ConsumerOptions, serve_jobs
from .claude import ClaudeChatModel
from .handler import NotesHandler, NotesResult, notes_failure
from .prompt import ContextBudget, PromptBuilder
from .settings import NotesSettings, NotesWorkerSettings, load_notes_worker_settings

NOTES_WORKER: Final = WorkerSpec(
    name="notes-worker",
    queue=NOTES_REQUESTS,
    kind=JobKind.NOTES,
    job_type=NotesRequested,
    failure_result=notes_failure,
)
_CONSUMER_TIMEOUT_MARGIN: Final = timedelta(minutes=5)


def build_runner(
    settings: NotesSettings, client: anthropic.AsyncAnthropic
) -> InlineRunner[NotesRequested, NotesResult]:
    model = ClaudeChatModel(
        client,
        model=settings.model,
        max_output_tokens=settings.max_output_tokens,
        effort=settings.effort,
    )
    builder = PromptBuilder(ContextBudget(settings.max_input_tokens, settings.chars_per_token))
    return InlineRunner(
        NOTES_WORKER, NotesHandler(builder, model).handle, timeout=settings.job_timeout
    )


async def serve(settings: NotesWorkerSettings) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signal_number, stop.set)
    notes = settings.notes
    options = ConsumerOptions(
        concurrency=notes.concurrency,
        consumer_timeout=notes.job_timeout + _CONSUMER_TIMEOUT_MARGIN,
        shutdown_grace=notes.shutdown_grace,
    )
    async with anthropic.AsyncAnthropic(
        api_key=notes.api_key.get_secret_value(), timeout=notes.job_timeout.total_seconds()
    ) as client:
        await serve_jobs(NOTES_WORKER, build_runner(notes, client), settings.broker, options, stop)


def main() -> None:
    settings = load_notes_worker_settings()
    configure_logging(settings.log_level)
    asyncio.run(serve(settings))
