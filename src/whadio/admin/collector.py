import asyncio
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..shared.telemetry import GpuObservation, Observation, ObservationPublisher, TelemetrySettings

logger = logging.getLogger(__name__)


class HostSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_MONITOR_", env_file=".env", extra="ignore"
    )
    volume: Path = Field(
        default=Path("/"), description="Host volume to measure; path is never published"
    )
    proc: Path = Field(
        default=Path("/proc"),
        description="Linux host proc filesystem, not a container process view",
    )


class HostCollector:
    def __init__(self, settings: HostSettings) -> None:
        self._settings: HostSettings = settings
        self._previous: tuple[int, int] | None = None

    def collect(self) -> Observation:
        proc = self._settings.proc
        counters = [
            int(value) for value in (proc / "stat").read_text().splitlines()[0].split()[1:9]
        ]
        total, idle = sum(counters), counters[3] + counters[4]
        previous = self._previous
        self._previous = total, idle
        cpu = None
        if previous is not None and total > previous[0]:
            cpu = max(0.0, min(100.0, 100 * (1 - (idle - previous[1]) / (total - previous[0]))))
        memory = {
            line.split(":")[0]: int(line.split()[1]) * 1024
            for line in (proc / "meminfo").read_text().splitlines()
            if len(line.split()) > 1
        }
        disk = shutil.disk_usage(self._settings.volume)
        return Observation(
            sampled_at=datetime.now(UTC),
            kind="host",
            cpu_percent=cpu,
            logical_cpus=os.cpu_count(),
            memory_used_bytes=memory["MemTotal"] - memory["MemAvailable"],
            memory_total_bytes=memory["MemTotal"],
            storage_used_bytes=disk.used,
            storage_total_bytes=disk.total,
        )


async def gpu_observations() -> list[GpuObservation] | None:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return None
    try:
        process = await asyncio.create_subprocess_exec(
            executable,
            "--query-gpu=utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return None

    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=2)
        if process.returncode != 0:
            return None
        return parse_gpu_observations(output)
    except (ValueError, IndexError, UnicodeError, TimeoutError):
        if process.returncode is None:
            process.kill()
            await process.wait()
        return None


def parse_gpu_observations(output: bytes) -> list[GpuObservation]:
    rows = [line.split(",") for line in output.decode().splitlines()]
    return [
        GpuObservation(
            device=f"gpu-{index}",
            utilization_percent=float(row[0]),
            memory_used_bytes=int(row[1]) * 1024 * 1024,
            memory_total_bytes=int(row[2]) * 1024 * 1024,
        )
        for index, row in enumerate(rows[:16])
    ]


async def collect_host(*, once: bool = False) -> None:
    settings = TelemetrySettings()
    if settings.receiver is None:
        raise ValueError(
            "Configure WHADIO_TELEMETRY_RECEIVER and TOKEN before starting the collector"
        )
    collector, publisher = HostCollector(HostSettings()), ObservationPublisher(settings)
    try:
        while True:
            try:
                observation = await asyncio.to_thread(collector.collect)
                observation.gpus = await gpu_observations()
                await publisher.publish(observation)
            except (OSError, ValueError, KeyError, IndexError):
                logger.warning("Host telemetry collection unavailable")
            if once:
                return
            await asyncio.sleep(settings.interval_seconds)
    finally:
        publisher.close()
