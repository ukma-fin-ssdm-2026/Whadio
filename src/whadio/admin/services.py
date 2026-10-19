import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

from pydantic import BaseModel, Field

from ..processing.monitoring import IJobMonitoring, JobCounts
from ..shared.errors import Failure, UseCaseError
from ..shared.telemetry import Observation, RuntimeAvailability
from .settings import AdminSettings

FRESH_SECONDS: Final = 30
UNAVAILABLE_SECONDS: Final = 90
EXPIRY_SECONDS: Final = 300


class SourceStatus(BaseModel):
    source_id: str = Field(description="Opaque configured source alias")
    state: Literal["fresh", "stale", "unavailable", "not_configured"] = Field(
        description=("Fresh <=30s; stale <=90s; unavailable thereafter; not_configured when absent")
    )
    sampled_at: datetime | None = Field(description="Last measurement time in UTC")
    last_success_at: datetime | None = Field(description="Last accepted publication time in UTC")
    error_code: (
        Literal["observation_stale", "observation_unavailable", "observation_incomplete"] | None
    ) = Field(
        description="Safe fixed collector condition, including fresh but incomplete measurements"
    )


class SourceObservation(BaseModel):
    source_id: str = Field(description="Source of these measurements")
    observation: Observation = Field(
        description=(
            "Latest accepted measurements; inspect source freshness and completeness before using"
        )
    )


class MetricsSnapshot(BaseModel):
    generated_at: datetime = Field(
        description="UTC assembly time; not a substitute for source sample times"
    )
    status: Literal["ok", "partial", "unavailable"] = Field(
        description="Overall snapshot completeness"
    )
    sources: list[SourceStatus] = Field(
        description="Freshness and availability of every configured source"
    )
    jobs: list[JobCounts] = Field(description="Logical-job aggregates from PostgreSQL")
    hosts: list[SourceObservation] = Field(
        description="Host measurements including retained stale values"
    )
    runtimes: list[SourceObservation] = Field(
        description="Actual ASR and deployment-selected Anthropic/Ollama worker measurements"
    )
    builtin_notes: RuntimeAvailability | Literal["not_configured"] = Field(
        default="not_configured",
        description=(
            "Observed local notes worker state; unknown for stale samples, unavailable "
            "after 90s; not_configured without a retained local notes observation. "
            "Worker readiness does not probe the Ollama server or model health"
        ),
    )


@dataclass(frozen=True)
class AcceptedObservation:
    value: Observation
    received_at: datetime


class ObservationStore:
    def __init__(self, settings: AdminSettings) -> None:
        self._settings: AdminSettings = settings
        self._samples: dict[str, AcceptedObservation] = {}
        self._watermarks: dict[str, datetime] = {}

    def authorized(self, source_id: str, token: str) -> bool:
        source = self._settings.sources.get(source_id)
        expected = source.token_hash if source is not None else "0" * 64
        matched = hmac.compare_digest(expected, hashlib.sha256(token.encode()).hexdigest())
        return source is not None and matched

    def accept(self, source_id: str, observation: Observation, now: datetime) -> None:
        source = self._settings.sources.get(source_id)
        if (
            source is None
            or source.kind != observation.kind
            or (source.kind == "runtime" and source.runtime != observation.runtime)
        ):
            raise UseCaseError(Failure.VALIDATION_ERROR)
        if not now - timedelta(minutes=5) <= observation.sampled_at <= now + timedelta(seconds=5):
            raise UseCaseError(Failure.VALIDATION_ERROR)
        previous = self._watermarks.get(source_id)
        if previous is not None and observation.sampled_at <= previous:
            raise UseCaseError(Failure.STALE_OBSERVATION)
        self._samples[source_id] = AcceptedObservation(observation, now)
        self._watermarks[source_id] = observation.sampled_at

    def observations(self, now: datetime) -> tuple[list[SourceStatus], list[SourceObservation]]:
        states: list[SourceStatus] = []
        values: list[SourceObservation] = []
        for source_id in self._settings.sources:
            sample = self._samples.get(source_id)
            if sample is not None and (now - sample.received_at).total_seconds() > EXPIRY_SECONDS:
                del self._samples[source_id]
                sample = None
            age = (
                float("inf")
                if sample is None
                else max(0.0, (now - sample.value.sampled_at).total_seconds())
            )
            state = (
                "fresh"
                if age <= FRESH_SECONDS
                else "stale"
                if age <= UNAVAILABLE_SECONDS
                else "unavailable"
            )
            states.append(
                SourceStatus(
                    source_id=source_id,
                    state=state,
                    sampled_at=None if sample is None else sample.value.sampled_at,
                    last_success_at=None if sample is None else sample.received_at,
                    error_code=(
                        None
                        if sample is not None and _complete(sample.value)
                        else "observation_incomplete"
                    )
                    if state == "fresh"
                    else "observation_stale"
                    if state == "stale"
                    else "observation_unavailable",
                )
            )
            if sample is not None:
                values.append(SourceObservation(source_id=source_id, observation=sample.value))
        return states, values


def _complete(observation: Observation) -> bool:
    if observation.kind == "host":
        measurements = (
            observation.cpu_percent,
            observation.logical_cpus,
            observation.memory_used_bytes,
            observation.memory_total_bytes,
            observation.storage_used_bytes,
            observation.storage_total_bytes,
        )
        return all(value is not None for value in measurements)
    return observation.availability == "ready" and all(
        value is not None
        for value in (
            observation.provider,
            observation.credential_origin,
            observation.model,
            observation.active,
            observation.capacity,
        )
    )


def _builtin_notes(
    states: list[SourceStatus], observations: list[SourceObservation]
) -> RuntimeAvailability | Literal["not_configured"]:
    sources = {source.source_id: source for source in states}
    local = [
        item
        for item in observations
        if item.observation.runtime == "notes" and item.observation.provider == "local"
    ]
    if not local:
        return "not_configured"
    availability: set[RuntimeAvailability] = set()
    for item in local:
        source = sources[item.source_id]
        if source.state == "unavailable":
            availability.add("unavailable")
        elif source.state != "fresh":
            availability.add("unknown")
        else:
            availability.add(item.observation.availability or "unknown")
    for state in ("ready", "loading", "unknown", "unavailable", "disabled"):
        if state in availability:
            return state
    return "unknown"


class AdminService:
    def __init__(self, jobs: IJobMonitoring, store: ObservationStore) -> None:
        self._jobs: IJobMonitoring = jobs
        self._store: ObservationStore = store

    async def metrics(self, now: datetime) -> MetricsSnapshot:
        jobs = await self._jobs.counts(now)
        states, observations = self._store.observations(now)
        return MetricsSnapshot(
            generated_at=now,
            status="ok"
            if states
            and all(source.state == "fresh" and source.error_code is None for source in states)
            else "partial",
            sources=states,
            jobs=jobs,
            builtin_notes=_builtin_notes(states, observations),
            hosts=[item for item in observations if item.observation.kind == "host"],
            runtimes=[item for item in observations if item.observation.kind == "runtime"],
        )
