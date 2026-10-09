import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ...contracts.common import Segment, Transcript
from ...contracts.notes import MeetingBrief, NotesPreset, NotesProvider, NotesRequested
from ...contracts.queues import NOTES_REQUESTS, PROCESSING_RESULTS, QueueSpec
from ...contracts.results import parse_result
from ...shared.broker import BrokerSettings, MessagePublisher, connect, declare_queue
from ..supervision.runners import InlineRunner
from ..supervision.supervisor import ConsumerOptions, serve_jobs
from .handler import NotesHandler
from .llm import Completion
from .main import NOTES_WORKER
from .prompt import ContextBudget, Prompt, PromptBuilder
from .settings import load_notes_worker_settings

_AT = datetime(2026, 10, 9, 18, tzinfo=UTC)
_NOTES = """\
# Sync

## Підсумок
- без змін.

## Рішення
—

## Завдання
—

## Відкриті питання
—
"""


class _FixedModel:
    @property
    def provider(self) -> NotesProvider:
        return NotesProvider.ANTHROPIC

    async def complete(self, prompt: Prompt) -> Completion:
        return Completion(text=_NOTES, model_name=f"fixed ({len(prompt.user)} chars)")


async def _run_one_job(broker: BrokerSettings, job: NotesRequested) -> list[str]:
    suffix = uuid4().hex
    spec = replace(
        NOTES_WORKER,
        queue=QueueSpec(f"test.notes.{suffix}", NOTES_REQUESTS.arguments),
        results=QueueSpec(f"test.results.{suffix}", PROCESSING_RESULTS.arguments),
    )
    builder = PromptBuilder(ContextBudget(max_input_tokens=100_000, chars_per_token=3.0))
    runner = InlineRunner(
        spec, NotesHandler(builder, _FixedModel()).handle, timeout=timedelta(seconds=10)
    )
    options = ConsumerOptions(
        concurrency=1, consumer_timeout=timedelta(minutes=1), shutdown_grace=timedelta(seconds=5)
    )
    stop = asyncio.Event()
    worker = asyncio.create_task(serve_jobs(spec, runner, broker, options, stop))
    types: list[str] = []
    async with await connect(broker, name="notes-worker-test") as connection:
        channel = await connection.channel()
        jobs = await declare_queue(channel, spec.queue.name, spec.queue.arguments)
        results = await declare_queue(channel, spec.results.name, spec.results.arguments)
        await MessagePublisher(channel, broker.user).publish(
            spec.queue.name,
            job.model_dump_json().encode(),
            message_type=job.type,
            correlation_id=str(job.job_id),
        )
        async with asyncio.timeout(30), results.iterator() as messages:
            async for message in messages:
                async with message.process():
                    types.append(parse_result(message.body).type)
                if len(types) == 2:
                    break
        stop.set()
        await worker
        await jobs.delete(if_unused=False, if_empty=False)
        await results.delete(if_unused=False, if_empty=False)
    return types


@pytest.mark.slow
def test_notes_worker_publishes_start_and_notes_of_a_job(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_NOTES__API_KEY", "not-used-by-the-fixed-model")
    broker = load_notes_worker_settings().broker
    job = NotesRequested(
        job_id=uuid4(),
        meeting_id=uuid4(),
        preset=NotesPreset.SUMMARY,
        meeting=MeetingBrief(name=None, recorded_at=_AT),
        transcript=Transcript(
            language="uk",
            speakers=("Speaker 1",),
            segments=(
                Segment(start_seconds=0, end_seconds=1, speaker="Speaker 1", text="Привіт."),
            ),
        ),
        context=(),
        glossary=(),
    )

    # Act
    types = asyncio.run(_run_one_job(broker, job))

    # Assert
    assert types == ["job_started", "notes_ready"]
