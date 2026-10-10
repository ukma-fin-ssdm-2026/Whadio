from datetime import timedelta
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ...contracts.common import LanguageCode
from ...shared.broker import BrokerSettings
from ...shared.logs import LogLevel
from .recognition import RecognizerKind


class ParakeetSettings(BaseModel):
    model: str = Field(
        default="nemo-parakeet-tdt-0.6b-v3", description="onnx-asr name of the Parakeet model"
    )
    quantization: Literal["int8"] | None = Field(
        default="int8", description="Quantization of the model; null for full precision"
    )


class WhisperSettings(BaseModel):
    model: str = Field(
        default="large-v2",
        description="faster-whisper model size or Hugging Face id; large-v3 recognises "
        "Ukrainian worse than large-v2",
    )
    compute_type: Literal["int8", "int8_float32", "int16", "float32"] = Field(
        default="int8", description="Precision of the CPU computation"
    )
    beam_size: int = Field(default=5, ge=1, description="Hypotheses kept while decoding")


class DiarizationSettings(BaseModel):
    model: str = Field(
        default="pyannote/speaker-diarization-community-1",
        description="pyannote.audio pipeline on the Hugging Face Hub",
    )
    hf_token: SecretStr | None = Field(
        default=None,
        description="Hugging Face token of an account that accepted the model's conditions; "
        "needed only while the model is not downloaded",
    )
    embedding_batch_size: int = Field(
        default=8, ge=1, description="Speaker embeddings computed in one batch"
    )


class AsrSettings(BaseModel):
    recognizer: RecognizerKind = Field(
        default=RecognizerKind.PARAKEET,
        description="Speech recognition model; only Whisper uses the workspace glossary",
    )
    parakeet: ParakeetSettings = Field(
        default_factory=ParakeetSettings, description="The Parakeet recognizer"
    )
    whisper: WhisperSettings = Field(
        default_factory=WhisperSettings, description="The Whisper recognizer"
    )
    diarization: DiarizationSettings = Field(
        default_factory=DiarizationSettings, description="The speaker diarization model"
    )
    languages: tuple[LanguageCode, ...] = Field(
        default=("uk", "en", "ru", "pl", "de", "fr", "es"),
        min_length=2,
        description="ISO 639-1 languages a transcript's language is chosen from when the job "
        "names none",
    )
    fallback_language: LanguageCode = Field(
        default="uk", description="Language of a transcript without words when the job names none"
    )
    max_audio_bytes: int = Field(
        default=500 * 1024 * 1024, ge=1, description="Largest recording the worker downloads"
    )
    max_duration: timedelta = Field(
        default=timedelta(hours=4), description="Longest recording the worker transcribes"
    )
    fetch_timeout: timedelta = Field(
        default=timedelta(minutes=1),
        description="Time a connection to storage, or a wait for its next bytes, may take",
    )
    slots: int = Field(
        default=1,
        ge=1,
        description="Jobs transcribed at the same time, each in a process with its own models",
    )
    job_timeout: timedelta = Field(
        default=timedelta(hours=2), description="Time after which a job is given up"
    )
    startup_timeout: timedelta = Field(
        default=timedelta(minutes=30),
        description="Time a process gets to load its models, downloading them on the first start",
    )
    shutdown_grace: timedelta = Field(
        default=timedelta(minutes=1), description="Time running jobs get to finish on shutdown"
    )


class AsrWorkerSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    log_level: LogLevel = Field(default="INFO", description="Lowest level of logged records")
    broker: BrokerSettings = Field(description="Connection to RabbitMQ")
    asr: AsrSettings = Field(
        default_factory=AsrSettings, description="The models and the job limits"
    )


def load_asr_worker_settings() -> AsrWorkerSettings:
    # Pyright gives a BaseSettings subclass a constructor that demands every field, although the
    # settings sources supply them; model_validate reads the same sources.
    return AsrWorkerSettings.model_validate({})
