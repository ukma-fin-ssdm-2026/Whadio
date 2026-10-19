import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ..processing.monitoring import JobCounts, JobFilter, JobSnapshot
from ..shared.errors import Failure, UseCaseError
from ..shared.pagination import ListWindow
from ..shared.telemetry import Observation, RuntimeActivity
from .services import AdminService, ObservationStore
from .settings import AdminSettings, SourceSettings

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def store_fixture() -> tuple[ObservationStore, str]:
    token = uuid4().hex
    source = SourceSettings(token_hash=hashlib.sha256(token.encode()).hexdigest(), kind="host")
    return ObservationStore(AdminSettings(sources={"main-host": source})), token


@pytest.mark.parametrize(
    ("seconds", "state"),
    [
        (0, "fresh"),
        (30, "fresh"),
        (31, "stale"),
        (90, "stale"),
        (91, "unavailable"),
        (300, "unavailable"),
    ],
)
def test_observation_freshness_uses_source_time(seconds: int, state: str) -> None:
    # Arrange
    store, _ = store_fixture()
    store.accept("main-host", Observation(sampled_at=NOW, kind="host", cpu_percent=20), NOW)
    # Act
    states, _ = store.observations(NOW + timedelta(seconds=seconds))
    # Assert
    assert states[0].state == state


def test_expired_observation_is_evicted_without_fabricated_values() -> None:
    # Arrange
    store, _ = store_fixture()
    store.accept("main-host", Observation(sampled_at=NOW, kind="host", cpu_percent=0), NOW)
    # Act
    states, values = store.observations(NOW + timedelta(seconds=301))
    # Assert
    assert (states[0].state, states[0].sampled_at, values) == ("unavailable", None, [])


@pytest.mark.parametrize("seconds", [-301, 6])
def test_observation_outside_clock_window_is_refused(seconds: int) -> None:
    # Arrange
    store, _ = store_fixture()
    # Act
    with pytest.raises(UseCaseError) as failure:
        store.accept(
            "main-host", Observation(sampled_at=NOW + timedelta(seconds=seconds), kind="host"), NOW
        )
    # Assert
    assert failure.value.code == Failure.VALIDATION_ERROR


def test_older_sample_cannot_replace_last_good_values() -> None:
    # Arrange
    store, _ = store_fixture()
    observation = Observation(sampled_at=NOW, kind="host", cpu_percent=10)
    store.accept("main-host", observation, NOW)
    # Act
    with pytest.raises(UseCaseError) as failure:
        store.accept("main-host", observation, NOW)
    # Assert
    assert failure.value.code == Failure.STALE_OBSERVATION


def test_host_credential_cannot_publish_worker_activity() -> None:
    # Arrange
    store, _ = store_fixture()
    # Act
    with pytest.raises(UseCaseError) as failure:
        store.accept(
            "main-host",
            Observation(sampled_at=NOW, kind="runtime", runtime="notes", availability="ready"),
            NOW,
        )
    # Assert
    assert failure.value.code == Failure.VALIDATION_ERROR


def test_source_credentials_are_bound_to_the_source() -> None:
    # Arrange
    store, token = store_fixture()
    # Act
    found = (
        store.authorized("main-host", token),
        store.authorized("other-host", token),
        store.authorized("main-host", uuid4().hex),
    )
    # Assert
    assert found == (True, False, False)


@pytest.mark.parametrize("cpu", [float("nan"), float("inf"), -1, 101])
def test_invalid_utilization_is_rejected(cpu: float) -> None:
    # Arrange
    # Act
    with pytest.raises(ValidationError) as failure:
        Observation(sampled_at=NOW, kind="host", cpu_percent=cpu)
    # Assert
    assert failure.value.error_count() == 1


def test_runtime_observation_identifies_actual_anthropic_execution() -> None:
    # Arrange
    activity = RuntimeActivity("notes", 4, "claude-test")
    activity.ready, activity.active = True, 2
    # Act
    observation = activity.observation()
    # Assert
    assert (
        observation.provider,
        observation.credential_origin,
        observation.active,
        observation.capacity,
    ) == ("anthropic", "deployment", 2, 4)


def test_external_notes_cannot_be_reported_as_builtin_usage() -> None:
    # Arrange
    # Act
    with pytest.raises(ValidationError) as failure:
        Observation(
            sampled_at=NOW,
            kind="runtime",
            runtime="notes",
            availability="ready",
            provider="local",
            credential_origin="deployment",
        )
    # Assert
    assert failure.value.error_count() == 1


class EmptyJobs:
    async def counts(self, now: datetime) -> list[JobCounts]:
        del now
        return []

    async def jobs(self, filters: JobFilter, page: ListWindow, now: datetime) -> list[JobSnapshot]:
        del filters, page, now
        return []


def host_observation() -> Observation:
    return Observation(
        sampled_at=NOW,
        kind="host",
        cpu_percent=0,
        logical_cpus=4,
        memory_used_bytes=0,
        memory_total_bytes=100,
        storage_used_bytes=0,
        storage_total_bytes=100,
    )


@pytest.mark.parametrize(
    "missing",
    [
        "cpu_percent",
        "logical_cpus",
        "memory_used_bytes",
        "memory_total_bytes",
        "storage_used_bytes",
        "storage_total_bytes",
    ],
)
def test_fresh_host_with_missing_measurement_is_partial(missing: str) -> None:
    # Arrange
    store, _ = store_fixture()
    observation = Observation.model_validate(host_observation().model_dump(exclude={missing}))
    store.accept("main-host", observation, NOW)
    # Act
    result = asyncio.run(AdminService(EmptyJobs(), store).metrics(NOW))
    # Assert
    assert (result.status, result.sources[0].state, result.sources[0].error_code) == (
        "partial",
        "fresh",
        "observation_incomplete",
    )


def test_fresh_complete_host_with_zero_usage_is_ok_without_gpu_measurements() -> None:
    # Arrange
    store, _ = store_fixture()
    store.accept("main-host", host_observation(), NOW)
    # Act
    result = asyncio.run(AdminService(EmptyJobs(), store).metrics(NOW))
    # Assert
    assert (result.status, result.sources[0].error_code) == ("ok", None)


def test_empty_sample_does_not_relabel_previous_measurements_as_fresh() -> None:
    # Arrange
    store, _ = store_fixture()
    store.accept("main-host", host_observation(), NOW)
    later = NOW + timedelta(seconds=10)
    store.accept("main-host", Observation(sampled_at=later, kind="host"), later)
    # Act
    result = asyncio.run(AdminService(EmptyJobs(), store).metrics(later))
    # Assert
    assert (result.status, result.sources[0].error_code, result.hosts[0].observation) == (
        "partial",
        "observation_incomplete",
        Observation(sampled_at=later, kind="host"),
    )


@pytest.mark.parametrize("availability", ["loading", "unavailable", "disabled", "unknown"])
def test_fresh_runtime_that_is_not_ready_is_partial(availability: str) -> None:
    # Arrange
    store = ObservationStore(
        AdminSettings(
            sources={"notes": SourceSettings(token_hash="0" * 64, kind="runtime", runtime="notes")}
        )
    )
    observation = Observation.model_validate(
        {"sampled_at": NOW, "kind": "runtime", "runtime": "notes", "availability": availability}
    )
    store.accept("notes", observation, NOW)
    # Act
    result = asyncio.run(AdminService(EmptyJobs(), store).metrics(NOW))
    # Assert
    assert (result.status, result.sources[0].state, result.sources[0].error_code) == (
        "partial",
        "fresh",
        "observation_incomplete",
    )


@pytest.mark.parametrize(
    "missing", ["provider", "credential_origin", "model", "active", "capacity"]
)
def test_ready_runtime_with_unknown_activity_or_identity_is_partial(missing: str) -> None:
    # Arrange
    store = ObservationStore(
        AdminSettings(
            sources={"notes": SourceSettings(token_hash="0" * 64, kind="runtime", runtime="notes")}
        )
    )
    activity = RuntimeActivity("notes", 4, "claude-test")
    activity.ready = True
    observation = Observation.model_validate(activity.observation().model_dump(exclude={missing}))
    store.accept("notes", observation, observation.sampled_at)
    # Act
    result = asyncio.run(AdminService(EmptyJobs(), store).metrics(observation.sampled_at))
    # Assert
    assert result.status == "partial"


def test_ready_runtime_with_known_idle_activity_is_ok() -> None:
    # Arrange
    store = ObservationStore(
        AdminSettings(
            sources={"notes": SourceSettings(token_hash="0" * 64, kind="runtime", runtime="notes")}
        )
    )
    activity = RuntimeActivity("notes", 4, "claude-test")
    activity.ready = True
    observation = activity.observation()
    store.accept("notes", observation, observation.sampled_at)
    # Act
    result = asyncio.run(AdminService(EmptyJobs(), store).metrics(observation.sampled_at))
    # Assert
    assert result.status == "ok"


@pytest.mark.parametrize(
    ("age", "expected"),
    [(0, "ready"), (30, "ready"), (31, "unknown"), (90, "unknown"), (91, "unavailable")],
)
def test_local_notes_worker_state_follows_source_freshness(age: int, expected: str) -> None:
    # Arrange
    store = ObservationStore(
        AdminSettings(
            sources={"notes": SourceSettings(token_hash="0" * 64, kind="runtime", runtime="notes")}
        )
    )
    activity = RuntimeActivity("notes", 2, "gemma3:12b", provider="local")
    activity.ready = True
    observation = activity.observation().model_copy(update={"sampled_at": NOW})
    store.accept("notes", observation, NOW)
    # Act
    result = asyncio.run(AdminService(EmptyJobs(), store).metrics(NOW + timedelta(seconds=age)))
    # Assert
    assert result.builtin_notes == expected


def test_anthropic_worker_does_not_count_as_local_notes() -> None:
    # Arrange
    store = ObservationStore(
        AdminSettings(
            sources={"notes": SourceSettings(token_hash="0" * 64, kind="runtime", runtime="notes")}
        )
    )
    activity = RuntimeActivity("notes", 2, "claude-test")
    activity.ready = True
    observation = activity.observation().model_copy(update={"sampled_at": NOW})
    store.accept("notes", observation, NOW)
    # Act
    result = asyncio.run(AdminService(EmptyJobs(), store).metrics(NOW))
    # Assert
    assert result.builtin_notes == "not_configured"


def test_local_notes_loading_is_not_reported_as_ready() -> None:
    # Arrange
    store = ObservationStore(
        AdminSettings(
            sources={"notes": SourceSettings(token_hash="0" * 64, kind="runtime", runtime="notes")}
        )
    )
    activity = RuntimeActivity("notes", 2, "gemma3:12b", provider="local")
    observation = activity.observation().model_copy(update={"sampled_at": NOW})
    store.accept("notes", observation, NOW)
    # Act
    result = asyncio.run(AdminService(EmptyJobs(), store).metrics(NOW))
    # Assert
    assert (result.builtin_notes, result.runtimes[0].observation.active) == ("loading", None)
