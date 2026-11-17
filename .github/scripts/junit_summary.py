import string
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _escape(text: str) -> str:
    return "".join(f"\\{char}" if char in string.punctuation else char for char in text)


def suite_totals(report: Path) -> str:
    suite = next(ET.parse(report).iter("testsuite"))
    count = int(suite.attrib["tests"])
    noun = "test" if count == 1 else "tests"
    return f"{count:,} {noun} in {float(suite.attrib['time']):.1f} s"


def failed_tests(report: Path) -> list[str]:
    lines: list[str] = []
    for case in ET.parse(report).iter("testcase"):
        for problem in [*case.iter("failure"), *case.iter("error")]:
            test_id = f"{case.get('classname', '')}::{case.get('name', '')}"
            message = (problem.get("message") or problem.tag).splitlines()[0]
            lines.append(f"- **{_escape(test_id)}**: {_escape(message)}")
    return lines


def main() -> None:
    report, suite = Path(sys.argv[1]), sys.argv[2]
    lines = failed_tests(report)
    sys.stdout.write(f"### {suite}\n\n{suite_totals(report)}.\n\n")
    sys.stdout.write("### Failed tests\n\n")
    sys.stdout.write("\n".join(lines) if lines else "No failed tests.")
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
