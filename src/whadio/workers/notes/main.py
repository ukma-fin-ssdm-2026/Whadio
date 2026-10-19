import asyncio
import signal
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Final

import anthropic
import httpx2

from ...contracts.common import JobKind
from ...contracts.notes import NotesRequested
from ...contracts.queues import NOTES_REQUESTS
from ...shared.logs import configure_logging
from ...shared.telemetry import RuntimeActivity
from ..supervision.jobs import WorkerSpec
from ..supervision.runners import InlineRunner
from ..supervision.supervisor import ConsumerOptions, serve_jobs
from .claude import ClaudeChatModel
from .handler import NotesHandler, NotesResult, notes_failure
from .llm import IChatModel
from .ollama import OllamaChatModel
from .prompt import ContextBudget, PromptBuilder
from .settings import (
    AnthropicSettings,
    NotesSettings,
    NotesWorkerSettings,
    OllamaSettings,
    load_notes_worker_settings,
)

NOTES_WORKER: Final = WorkerSpec(
    name="notes-worker",
    queue=NOTES_REQUESTS,
    kind=JobKind.NOTES,
    job_type=NotesRequested,
    failure_result=notes_failure,
)
_CONSUMER_TIMEOUT_MARGIN: Final = timedelta(minutes=5)


@asynccontextmanager
async def open_chat_model(settings: NotesSettings) -> AsyncGenerator[IChatModel]:
    timeout = settings.job_timeout.total_seconds()
    match settings.llm:
        case AnthropicSettings() as llm:
            async with anthropic.AsyncAnthropic(
                api_key=llm.api_key.get_secret_value(), timeout=timeout
            ) as client:
                yield ClaudeChatModel(
                    client,
                    model=llm.model,
                    max_output_tokens=settings.max_output_tokens,
                    effort=llm.effort,
                )
        case OllamaSettings() as llm:
            async with httpx2.AsyncClient(base_url=str(llm.base_url), timeout=timeout) as client:
                yield OllamaChatModel(
                    client,
                    model=llm.model,
                    num_ctx=llm.num_ctx,
                    num_predict=settings.max_output_tokens,
                    keep_alive=llm.keep_alive,
                )


def build_runner(
    settings: NotesSettings, model: IChatModel
) -> InlineRunner[NotesRequested, NotesResult]:
    builder = PromptBuilder(ContextBudget(settings.max_prompt_tokens, settings.chars_per_token))
    return InlineRunner(
        NOTES_WORKER, NotesHandler(builder, model).handle, timeout=settings.job_timeout
    )


def build_activity(settings: NotesSettings) -> RuntimeActivity:
    return RuntimeActivity(
        "notes",
        settings.concurrency,
        settings.llm.model,
        provider="local" if isinstance(settings.llm, OllamaSettings) else "anthropic",
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
        activity=build_activity(notes),
    )
    async with open_chat_model(notes) as model:
        await serve_jobs(NOTES_WORKER, build_runner(notes, model), settings.broker, options, stop)


def main() -> None:
    settings = load_notes_worker_settings()
    configure_logging(settings.log_level)
    asyncio.run(serve(settings))
