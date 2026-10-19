import asyncio
from pathlib import Path

import pytest

from .collector import HostCollector, HostSettings, gpu_observations, parse_gpu_observations


def test_host_cpu_uses_interval_deltas_and_memory_has_a_denominator(tmp_path: Path) -> None:
    # Arrange
    stat = tmp_path / "stat"
    stat.write_text("cpu  20 0 20 50 10 0 0 0\n")
    (tmp_path / "meminfo").write_text("MemTotal: 100 kB\nMemAvailable: 40 kB\n")
    collector = HostCollector(HostSettings(proc=tmp_path, volume=tmp_path))
    first = collector.collect()
    stat.write_text("cpu  50 0 50 80 20 0 0 0\n")
    # Act
    second = collector.collect()
    # Assert
    assert (
        first.cpu_percent,
        second.cpu_percent,
        second.memory_used_bytes,
        second.memory_total_bytes,
    ) == (None, 60, 60 * 1024, 100 * 1024)


def test_unsupported_gpu_collection_is_unknown_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    def unavailable(_command: str) -> None:
        return None

    monkeypatch.setattr("whadio.admin.collector.shutil.which", unavailable)
    # Act
    found = asyncio.run(gpu_observations())
    # Assert
    assert found is None


def test_nvidia_metrics_use_opaque_aliases_and_convert_mib_to_bytes() -> None:
    # Arrange
    output = b"25, 1024, 8192\n0, 0, 4096\n"
    # Act
    values = parse_gpu_observations(output)
    # Assert
    assert [
        (value.device, value.utilization_percent, value.memory_used_bytes, value.memory_total_bytes)
        for value in values
    ] == [
        ("gpu-0", 25, 1024 * 1024 * 1024, 8192 * 1024 * 1024),
        ("gpu-1", 0, 0, 4096 * 1024 * 1024),
    ]
