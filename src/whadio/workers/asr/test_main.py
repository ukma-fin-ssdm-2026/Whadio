import asyncio
import io
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

import httpx2
import pytest
from pydantic import Field, HttpUrl, SecretStr, TypeAdapter
from pydantic_settings import BaseSettings, SettingsConfigDict

from ...contracts.queues import PROCESSING_RESULTS, TRANSCRIPTION_REQUESTS, QueueSpec
from ...contracts.results import parse_result
from ...contracts.transcription import AudioLink, TranscriptionRequested
from ...shared.broker import BrokerSettings, MessagePublisher, connect, declare_queue
from ...shared.storage import ObjectStorageSettings, connect_s3_storage
from ..supervision.slots import ProcessSlot, SlotPool, slot_program
from ..supervision.supervisor import ConsumerOptions, serve_jobs
from .audio import Audio, AudioDecoder, AudioFetcher, AudioLoader
from .diarization import SpeakerTurn
from .language import TranscriptLanguage
from .main import ASR_WORKER
from .pipeline import TranscriptionPipeline, TranscriptionResult
from .recognition import RecognitionHints, RecognizedSegment

_CLIP = Path(__file__).parent / "testdata" / "en-2277-149896-0032.flac"


class _StackSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_file=".env", extra="ignore")

    s3_access_key: SecretStr = Field(description="Access key of the Compose stack's SeaweedFS")
    s3_secret_key: SecretStr = Field(description="Secret key of the Compose stack's SeaweedFS")


class _Diarizer:
    def diarize(self, audio: Audio) -> tuple[SpeakerTurn, ...]:
        return (SpeakerTurn(start=0.0, end=audio.duration_seconds, speaker="SPEAKER_00"),)


class _Recognizer:
    @property
    def model_name(self) -> str:
        return "fake-asr"

    def recognize(self, audio: Audio, hints: RecognitionHints) -> tuple[RecognizedSegment, ...]:
        del hints
        text = "By the time he reached his own street."
        return (RecognizedSegment(start=0.0, end=audio.duration_seconds, text=text, words=()),)


def _build_handler() -> Callable[[TranscriptionRequested], TranscriptionResult]:
    pipeline = TranscriptionPipeline(
        audio=AudioLoader(
            AudioFetcher(httpx2.Client(timeout=30), max_bytes=10_000_000),
            AudioDecoder(max_duration=timedelta(minutes=1)),
        ),
        diarizer=_Diarizer(),
        recognizer=_Recognizer(),
        language=TranscriptLanguage(("uk", "en"), fallback="uk"),
    )
    return pipeline.run


async def _run_one_job(broker: BrokerSettings, job: TranscriptionRequested) -> list[str]:
    suffix = uuid4().hex
    spec = replace(
        ASR_WORKER,
        queue=QueueSpec(f"test.transcription.{suffix}", TRANSCRIPTION_REQUESTS.arguments),
        results=QueueSpec(f"test.results.{suffix}", PROCESSING_RESULTS.arguments),
    )
    runner = SlotPool(
        [
            ProcessSlot(
                slot_program(spec, _build_handler),
                TypeAdapter[TranscriptionResult](TranscriptionResult),
                timeout=timedelta(minutes=1),
                startup_timeout=timedelta(minutes=1),
            )
        ]
    )
    options = ConsumerOptions(
        concurrency=1, consumer_timeout=timedelta(minutes=5), shutdown_grace=timedelta(seconds=5)
    )
    stop = asyncio.Event()
    worker = asyncio.create_task(serve_jobs(spec, runner, broker, options, stop))
    types: list[str] = []
    async with await connect(broker, name="asr-worker-test") as connection:
        channel = await connection.channel()
        jobs = await declare_queue(channel, spec.queue.name, spec.queue.arguments)
        results = await declare_queue(channel, spec.results.name, spec.results.arguments)
        await MessagePublisher(channel, broker.user).publish(
            spec.queue.name,
            job.model_dump_json().encode(),
            message_type=job.type,
            correlation_id=str(job.job_id),
        )
        async with asyncio.timeout(120), results.iterator() as messages:
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
def test_asr_worker_transcribes_a_recording_from_its_presigned_url(
    rabbitmq_settings: BrokerSettings,
) -> None:
    # Arrange
    stack = _StackSettings.model_validate({})
    storage = connect_s3_storage(
        ObjectStorageSettings(
            endpoint_url=HttpUrl("http://localhost:8333"),
            access_key=stack.s3_access_key,
            secret_key=stack.s3_secret_key,
        )
    )
    key = f"test/{uuid4().hex}.flac"
    storage.put(key, io.BytesIO(_CLIP.read_bytes()), content_type="audio/flac")
    presigned = storage.presign_get(key, expires_in=timedelta(minutes=10))
    job = TranscriptionRequested(
        job_id=uuid4(),
        meeting_id=uuid4(),
        audio=AudioLink(url=HttpUrl(presigned.url), expires_at=presigned.expires_at),
        language=None,
        glossary=(),
    )

    # Act
    try:
        types = asyncio.run(_run_one_job(rabbitmq_settings, job))
    finally:
        storage.delete(key)

    # Assert
    assert types == ["job_started", "transcript_ready"]
