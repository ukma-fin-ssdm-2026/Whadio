import asyncio
import signal
from datetime import timedelta
from functools import partial
from typing import Final

from pydantic import TypeAdapter

from ...contracts.common import JobKind
from ...contracts.queues import TRANSCRIPTION_REQUESTS
from ...contracts.transcription import TranscriptionRequested
from ...shared.logs import configure_logging
from ...shared.telemetry import RuntimeActivity
from ..supervision.jobs import WorkerSpec
from ..supervision.slots import ProcessSlot, SlotPool, slot_program
from ..supervision.supervisor import ConsumerOptions, serve_jobs
from .pipeline import TranscriptionResult, transcription_failure
from .settings import AsrWorkerSettings, load_asr_worker_settings
from .slot import build_transcriber

ASR_WORKER: Final = WorkerSpec(
    name="asr-worker",
    queue=TRANSCRIPTION_REQUESTS,
    kind=JobKind.TRANSCRIPTION,
    job_type=TranscriptionRequested,
    failure_result=transcription_failure,
)
_RESULTS: Final = TypeAdapter[TranscriptionResult](TranscriptionResult)
_CONSUMER_TIMEOUT_MARGIN: Final = timedelta(minutes=5)


def build_runner(
    settings: AsrWorkerSettings,
) -> SlotPool[TranscriptionRequested, TranscriptionResult]:
    asr = settings.asr
    program = slot_program(ASR_WORKER, partial(build_transcriber, asr, settings.log_level))
    return SlotPool(
        [
            ProcessSlot(
                program, _RESULTS, timeout=asr.job_timeout, startup_timeout=asr.startup_timeout
            )
            for _ in range(asr.slots)
        ]
    )


async def serve(settings: AsrWorkerSettings) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signal_number, stop.set)
    asr = settings.asr
    runner = build_runner(settings)
    options = ConsumerOptions(
        concurrency=asr.slots,
        # A job first waits for its slot to restart a process that crashed or overran.
        consumer_timeout=asr.startup_timeout + asr.job_timeout + _CONSUMER_TIMEOUT_MARGIN,
        shutdown_grace=asr.shutdown_grace,
        activity=RuntimeActivity(
            "asr",
            settings.asr.slots,
            settings.asr.parakeet.model
            if settings.asr.recognizer.value == "parakeet"
            else settings.asr.whisper.model,
            availability=lambda: runner.availability,
        ),
    )
    await serve_jobs(
        ASR_WORKER,
        runner,
        settings.broker,
        options,
        stop,
    )


def main() -> None:
    settings = load_asr_worker_settings()
    configure_logging(settings.log_level)
    asyncio.run(serve(settings))
