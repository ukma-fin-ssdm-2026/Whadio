import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load() -> ModuleType:
    path = Path(__file__).with_name("code_changes.py")
    spec = importlib.util.spec_from_file_location("code_changes", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


changes = _load()


@pytest.mark.parametrize(
    "path",
    [
        "docs/testing/testing.md",
        "docs/api/openapi-generated.json",
        "Labs/Lab06/video_member.txt",
        ".agents/skills/pr-review/SKILL.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
        "README.md",
        "CHANGELOG.md",
    ],
)
def test_documentation_paths_are_documentation(path: str) -> None:
    # Act
    result = changes.is_documentation(path)

    # Assert
    assert result is True


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        ".github/workflows/ci.yml",
        ".github/scripts/code_changes.py",
        ".claude/skills",
        "tests/performance/README.md",
        "src/whadio/api/meetings/testdata/NOTICE.md",
        "frontend/src/app/App.tsx",
        "pyproject.toml",
        "docs.md.bak",
        "docsite/index.md",
        "Labs.txt",
    ],
)
def test_other_paths_are_code(path: str) -> None:
    # Act
    result = changes.is_documentation(path)

    # Assert
    assert result is False


def test_a_change_to_documentation_alone_touches_no_code() -> None:
    # Arrange
    paths = ["docs/testing/testing.md", "AGENTS.md", "Labs/Lab06/video_member.txt"]

    # Act
    result = changes.touches_code(paths)

    # Assert
    assert result is False


def test_one_code_file_among_documentation_touches_code() -> None:
    # Arrange
    paths = ["docs/testing/testing.md", ".env.example", "AGENTS.md"]

    # Act
    result = changes.touches_code(paths)

    # Assert
    assert result is True


def test_an_empty_change_touches_code() -> None:
    # Act
    result = changes.touches_code([])

    # Assert
    assert result is True


@pytest.mark.parametrize(
    ("stdin", "expected"),
    [
        ("docs/testing/testing.md\n\nREADME.md\n", "false\n"),
        ("docs/testing/testing.md\nsrc/whadio/cli.py\n", "true\n"),
        ("", "true\n"),
    ],
)
def test_main_prints_whether_the_paths_on_stdin_touch_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], stdin: str, expected: str
) -> None:
    # Arrange
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))

    # Act
    changes.main()

    # Assert
    assert capsys.readouterr().out == expected
