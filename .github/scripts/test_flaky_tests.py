import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Literal

import pytest

type Kind = Literal["passed", "failed", "error", "skipped"]
type Run = list[tuple[str, Kind]]

TEST_A = "app.test_x::test_a"
ESCAPED_A = "app\\.test\\_x\\:\\:test\\_a"
BODIES: dict[Kind, str] = {
    "passed": "",
    "failed": '<failure message="assert False"/>',
    "error": '<error message="fixture failed"/>',
    "skipped": '<skipped message="not on Linux"/>',
}


def _load() -> ModuleType:
    path = Path(__file__).with_name("flaky_tests.py")
    spec = importlib.util.spec_from_file_location("flaky_tests", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


flaky_tests = _load()


def _write(directory: Path, cases: Run, report: str = "backend.xml", suite: str = "pytest") -> None:
    directory.mkdir(exist_ok=True)
    body = "".join(
        f'<testcase classname="app.test_x" name="{name}">{BODIES[kind]}</testcase>'
        for name, kind in cases
    )
    (directory / report).write_text(
        f'<testsuites><testsuite name="{suite}">{body}</testsuite></testsuites>', encoding="utf-8"
    )


def _repeats(root: Path, *runs: Run, suite: str = "pytest") -> list[Path]:
    directories = [root / f"repeat-{number}" for number in range(len(runs))]
    for directory, cases in zip(directories, runs, strict=True):
        _write(directory, cases, suite=suite)
    return directories


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        pytest.param("passed", "passed", id="no-child-passed"),
        pytest.param("failed", "failed", id="failure-failed"),
        pytest.param("error", "failed", id="error-failed"),
        pytest.param("skipped", "skipped", id="skipped-skipped"),
    ],
)
def test_testcase_outcome_comes_from_its_child_element(
    tmp_path: Path, kind: Kind, expected: str
) -> None:
    # Arrange
    _write(tmp_path, [("test_a", kind)])

    # Act
    outcomes = flaky_tests.read_repeat(tmp_path)

    # Assert
    assert outcomes == {TEST_A: expected}


def test_failure_of_a_repeated_pytest_id_keeps_the_repeat_failed(tmp_path: Path) -> None:
    # Arrange
    _write(tmp_path, [("test_a", "failed"), ("test_a", "passed")])

    # Act
    outcomes = flaky_tests.read_repeat(tmp_path)

    # Assert
    assert outcomes == {TEST_A: "failed"}


def test_same_titled_vitest_cases_that_take_turns_failing_are_both_flaky(tmp_path: Path) -> None:
    # Arrange
    directories = _repeats(
        tmp_path,
        [("test_a", "failed"), ("test_a", "passed")],
        [("test_a", "passed"), ("test_a", "failed")],
        suite="popup.test.js",
    )

    # Act
    flaky = flaky_tests.flaky(flaky_tests.compare(directories))

    # Assert
    assert flaky == [TEST_A, f"{TEST_A} #2"]


def test_every_report_of_a_repeat_is_read(tmp_path: Path) -> None:
    # Arrange
    _write(tmp_path, [("test_a", "passed")])
    _write(tmp_path, [("test_b", "passed")], report="frontend.xml")

    # Act
    outcomes = flaky_tests.read_repeat(tmp_path)

    # Assert
    assert sorted(outcomes) == [TEST_A, "app.test_x::test_b"]


def test_repeat_without_a_report_is_refused(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "notes.txt").write_text("no reports here", encoding="utf-8")

    # Act / Assert
    with pytest.raises(FileNotFoundError, match="no JUnit report"):
        flaky_tests.read_repeat(tmp_path)


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        pytest.param("passed", "failed", [TEST_A], id="passed-then-failed"),
        pytest.param("error", "passed", [TEST_A], id="error-then-passed"),
        pytest.param("passed", "skipped", [TEST_A], id="passed-then-skipped"),
        pytest.param("passed", "passed", [], id="always-passed"),
        pytest.param("failed", "error", [], id="always-failed"),
        pytest.param("skipped", "skipped", [], id="always-skipped"),
    ],
)
def test_test_is_flaky_only_when_its_outcome_differed(
    tmp_path: Path, first: Kind, second: Kind, expected: list[str]
) -> None:
    # Arrange
    directories = _repeats(tmp_path, [("test_a", first)], [("test_a", second)])

    # Act
    flaky = flaky_tests.flaky(flaky_tests.compare(directories))

    # Assert
    assert flaky == expected


def test_test_missing_from_one_repeat_is_flaky(tmp_path: Path) -> None:
    # Arrange
    directories = _repeats(
        tmp_path, [("test_a", "passed"), ("test_b", "passed")], [("test_b", "passed")]
    )

    # Act
    flaky = flaky_tests.flaky(flaky_tests.compare(directories))

    # Assert
    assert flaky == [TEST_A]


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        pytest.param("failed", "error", [TEST_A], id="failed-every-time"),
        pytest.param("failed", "passed", [], id="failed-once"),
        pytest.param("passed", "passed", [], id="never-failed"),
    ],
)
def test_only_a_test_that_failed_every_repeat_is_consistently_failing(
    tmp_path: Path, first: Kind, second: Kind, expected: list[str]
) -> None:
    # Arrange
    directories = _repeats(tmp_path, [("test_a", first)], [("test_a", second)])

    # Act
    failing = flaky_tests.always_failing(flaky_tests.compare(directories))

    # Assert
    assert failing == expected


def test_summary_counts_each_outcome_of_a_flaky_test(tmp_path: Path) -> None:
    # Arrange
    directories = _repeats(
        tmp_path, [("test_a", "passed")], [("test_a", "failed")], [("test_a", "failed")], []
    )

    # Act
    summary = flaky_tests.summary(flaky_tests.compare(directories), 4)

    # Assert
    assert f"| {ESCAPED_A} | 1 | 2 | 0 | 1 |" in summary.splitlines()


def test_summary_lists_a_consistently_failing_test(tmp_path: Path) -> None:
    # Arrange
    directories = _repeats(tmp_path, [("test_a", "failed")], [("test_a", "failed")])

    # Act
    summary = flaky_tests.summary(flaky_tests.compare(directories), 2)

    # Assert
    assert f"- {ESCAPED_A}" in summary.splitlines()


def test_summary_of_stable_tests_reports_no_flaky_and_no_failing_test(tmp_path: Path) -> None:
    # Arrange
    directories = _repeats(tmp_path, [("test_a", "passed")], [("test_a", "passed")])

    # Act
    summary = flaky_tests.summary(flaky_tests.compare(directories), 2)

    # Assert
    assert summary == (
        "### Flaky tests\n\nNo test changed its outcome between repeats.\n\n"
        "### Consistently failing tests\n\nNo test failed every time.\n\n"
        "**Repeats: 2. Tests: 1. Flaky: 0. Consistently failing: 0.**\n"
    )


def test_flaky_test_fails_the_comparison(tmp_path: Path) -> None:
    # Arrange
    directories = _repeats(tmp_path, [("test_a", "passed")], [("test_a", "failed")])

    # Act
    status = flaky_tests.main(directories)

    # Assert
    assert status == 1


def test_consistently_failing_test_alone_passes_the_comparison(tmp_path: Path) -> None:
    # Arrange
    directories = _repeats(tmp_path, [("test_a", "failed")], [("test_a", "failed")])

    # Act
    status = flaky_tests.main(directories)

    # Assert
    assert status == 0
