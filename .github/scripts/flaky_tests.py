import string
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple


class Outcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    MISSING = "missing"


class CaseId(NamedTuple):
    classname: str
    name: str
    occurrence: int

    @property
    def label(self) -> str:
        suffix = f" #{self.occurrence}" if self.occurrence > 1 else ""
        return f"{self.classname}::{self.name}{suffix}"


def _escape(text: str) -> str:
    return "".join(f"\\{char}" if char in string.punctuation else char for char in text)


def _outcome(case: ET.Element) -> Outcome:
    if case.find("failure") is not None or case.find("error") is not None:
        return Outcome.FAILED
    if case.find("skipped") is not None:
        return Outcome.SKIPPED
    return Outcome.PASSED


def _cases(report: Path) -> Iterator[tuple[CaseId, Outcome]]:
    root = ET.parse(report).getroot()
    # Only pytest repeats an id for one test: a failed call, then its teardown error.
    from_pytest = any(suite.get("name") == "pytest" for suite in root.iter("testsuite"))
    occurrences: Counter[tuple[str, str]] = Counter()
    for case in root.iter("testcase"):
        classname, name = case.get("classname", ""), case.get("name", "")
        occurrences[classname, name] += 1
        occurrence = 1 if from_pytest else occurrences[classname, name]
        yield CaseId(classname, name, occurrence), _outcome(case)


def read_repeat(directory: Path) -> dict[CaseId, Outcome]:
    reports = sorted(directory.glob("*.xml"))
    if not reports:
        raise FileNotFoundError(f"{directory} holds no JUnit report")
    outcomes: dict[CaseId, Outcome] = {}
    for report in reports:
        for test_id, outcome in _cases(report):
            if outcomes.get(test_id) is not Outcome.FAILED:
                outcomes[test_id] = outcome
    return outcomes


def compare(directories: list[Path]) -> dict[CaseId, Counter[Outcome]]:
    repeats = [read_repeat(directory) for directory in directories]
    test_ids = sorted({test_id for repeat in repeats for test_id in repeat})
    return {
        test_id: Counter(repeat.get(test_id, Outcome.MISSING) for repeat in repeats)
        for test_id in test_ids
    }


def flaky(results: dict[CaseId, Counter[Outcome]]) -> list[CaseId]:
    return [test_id for test_id, counts in results.items() if len(counts) > 1]


def always_failing(results: dict[CaseId, Counter[Outcome]]) -> list[CaseId]:
    return [test_id for test_id, counts in results.items() if counts.keys() == {Outcome.FAILED}]


def summary(results: dict[CaseId, Counter[Outcome]], repeats: int) -> str:
    flaky_ids = flaky(results)
    failing_ids = always_failing(results)
    lines = ["### Flaky tests", ""]
    if flaky_ids:
        lines += [
            "| Test | " + " | ".join(outcome.capitalize() for outcome in Outcome) + " |",
            "| --- |" + " ---: |" * len(Outcome),
        ]
        lines += [
            f"| {_escape(test_id.label)} | "
            + " | ".join(str(results[test_id][outcome]) for outcome in Outcome)
            + " |"
            for test_id in flaky_ids
        ]
    else:
        lines.append("No test changed its outcome between repeats.")
    lines += ["", "### Consistently failing tests", ""]
    lines += [f"- {_escape(case.label)}" for case in failing_ids] or ["No test failed every time."]
    lines += [
        "",
        (
            f"**Repeats: {repeats}. Tests: {len(results)}. Flaky: {len(flaky_ids)}."
            f" Consistently failing: {len(failing_ids)}.**"
        ),
    ]
    return "\n".join(lines) + "\n"


def main(directories: list[Path]) -> int:
    """Compare repeats, one directory of JUnit reports each; return 1 if any test was flaky."""
    results = compare(directories)
    sys.stdout.write(summary(results, len(directories)))
    return 1 if flaky(results) else 0


if __name__ == "__main__":
    sys.exit(main([Path(argument) for argument in sys.argv[1:]]))
