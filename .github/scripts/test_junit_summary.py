import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load() -> ModuleType:
    path = Path(__file__).with_name("junit_summary.py")
    spec = importlib.util.spec_from_file_location("junit_summary", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


summary = _load()


@pytest.mark.parametrize(
    ("tests", "time", "expected"),
    [("1223", "23.944", "1,223 tests in 23.9 s"), ("1", "0.04", "1 test in 0.0 s")],
)
def test_suite_totals_states_the_count_and_the_duration(
    tmp_path: Path, tests: str, time: str, expected: str
) -> None:
    # Arrange
    report = tmp_path / "junit.xml"
    report.write_text(
        f'<testsuites><testsuite name="pytest" tests="{tests}" time="{time}"/></testsuites>'
    )

    # Act
    result = summary.suite_totals(report)

    # Assert
    assert result == expected


def test_suite_totals_refuses_a_suite_without_a_count(tmp_path: Path) -> None:
    # Arrange
    report = tmp_path / "junit.xml"
    report.write_text('<testsuites><testsuite name="pytest" time="1.0"/></testsuites>')

    # Act / Assert
    with pytest.raises(KeyError):
        summary.suite_totals(report)
