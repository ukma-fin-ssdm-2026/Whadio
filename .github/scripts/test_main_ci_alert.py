import importlib.util
import io
import json
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPOSITORY_URL = "https://github.com/org/repo"
COMMIT = "ae00e35938fadd6b14db07482758ecd008f2fde7"
RUN_ID = 40963978557


def _load() -> ModuleType:
    path = Path(__file__).with_name("main_ci_alert.py")
    spec = importlib.util.spec_from_file_location("main_ci_alert", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


alert = _load()


def _write_event(path: Path, **fields: object) -> None:
    workflow_run = {
        "id": RUN_ID,
        "run_attempt": 1,
        "head_sha": COMMIT,
        "conclusion": "failure",
        "head_branch": "main",
        "head_repository": {"full_name": "org/repo"},
        "event": "push",
    }
    path.write_text(json.dumps({"workflow_run": workflow_run | fields}), encoding="utf-8")


@pytest.fixture
def event_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    event = tmp_path / "event.json"
    for name, value in {
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "org/repo",
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_CHAT_ID": "42",
    }.items():
        monkeypatch.setenv(name, value)
    return event


@pytest.fixture
def alert_workflow() -> object:
    workflow = Path(__file__).parents[1] / "workflows" / "main-ci-alert.yml"
    return yaml.safe_load(workflow.read_text(encoding="utf-8"))


# PyYAML interprets an unquoted `on` key as the YAML 1.1 boolean true.
def test_alert_workflow_subscribes_to_ci_completions_on_main(alert_workflow: object) -> None:
    # Arrange
    expected = {"workflows": ["CI/CD"], "types": ["completed"], "branches": ["main"]}

    # Act
    match alert_workflow:
        case {"on": {"workflow_run": trigger}} | {True: {"workflow_run": trigger}}:
            actual = trigger
        case _:
            pytest.fail("The alert workflow is missing its CI completion trigger.")

    # Assert
    assert actual == expected


def test_alert_workflow_runs_the_sender_with_the_existing_secrets(alert_workflow: object) -> None:
    # Arrange
    expected = {
        "TELEGRAM_BOT_TOKEN": "${{ secrets.TELEGRAM_BOT_TOKEN }}",
        "TELEGRAM_CHAT_ID": "${{ secrets.TELEGRAM_CHAT_ID }}",
    }

    # Act
    match alert_workflow:
        case {
            "jobs": {
                "notify": {
                    "steps": [
                        *_,
                        {"run": "python3 -I .github/scripts/main_ci_alert.py", "env": bindings},
                    ],
                },
            },
        }:
            actual = bindings
        case _:
            pytest.fail("The alert workflow is missing the sender step or its secrets.")

    # Assert
    assert actual == expected


@pytest.mark.parametrize(
    ("source", "attempt"), [("push", 1), ("push", 2), ("workflow_dispatch", 1)]
)
def test_alert_links_to_the_commit_and_exact_failed_attempt(
    event_path: Path, monkeypatch: pytest.MonkeyPatch, source: str, attempt: int
) -> None:
    # Arrange
    sent: list[tuple[str, str, int, object]] = []

    def deliver(request: urllib.request.Request, *, timeout: int) -> io.BytesIO:
        assert isinstance(request.data, bytes)
        sent.append((request.get_method(), request.full_url, timeout, json.loads(request.data)))
        return io.BytesIO(b'{"ok": true}')

    _write_event(event_path, event=source, run_attempt=attempt)
    monkeypatch.setattr(urllib.request, "urlopen", deliver)

    # Act
    alert.main()

    # Assert
    assert sent == [
        (
            "POST",
            "https://api.telegram.org/bottest-token/sendMessage",
            30,
            {
                "chat_id": "42",
                "text": (
                    "🔴 Whadio CI/CD failed on main\n"
                    f'Commit <a href="{REPOSITORY_URL}/commit/{COMMIT}">ae00e35</a>\n'
                    f'<a href="{REPOSITORY_URL}/actions/runs/{RUN_ID}/attempts/{attempt}">'
                    f"View failed CI run (attempt {attempt})</a>"
                ),
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            },
        )
    ]


def _unexpected_request(_request: urllib.request.Request, **_options: int) -> io.BytesIO:
    pytest.fail("The sender should stop before making a Telegram request.")


@pytest.mark.parametrize(
    "fields",
    [
        {"event": "pull_request"},
        {"head_branch": "feature"},
        {"head_repository": {"full_name": "fork/repo"}},
        {"conclusion": "success"},
        {"conclusion": "cancelled"},
    ],
    ids=["pull request", "other branch", "fork", "success", "cancelled"],
)
def test_alert_skips_runs_outside_the_failed_main_policy(
    event_path: Path, monkeypatch: pytest.MonkeyPatch, fields: dict[str, object]
) -> None:
    # Arrange
    _write_event(event_path, **fields)
    monkeypatch.setattr(urllib.request, "urlopen", _unexpected_request)

    # Act
    result = alert.main()

    # Assert
    assert result is None


def test_alert_rejects_a_failed_run_without_attempt_metadata(
    event_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _write_event(event_path, run_attempt=None)
    monkeypatch.setattr(urllib.request, "urlopen", _unexpected_request)

    # Act
    with pytest.raises(SystemExit) as error:
        alert.main()

    # Assert
    assert str(error.value) == "GitHub event is missing failed run metadata."


def test_alert_reports_invalid_event_json(
    event_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    event_path.write_text("not JSON", encoding="utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", _unexpected_request)

    # Act
    with pytest.raises(SystemExit) as error:
        alert.main()

    # Assert
    assert str(error.value) == "Could not read the GitHub event: JSONDecodeError."


@pytest.mark.parametrize("secret", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
def test_alert_stops_before_contacting_telegram_when_a_secret_is_empty(
    event_path: Path, monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    # Arrange
    _write_event(event_path)
    monkeypatch.setenv(secret, "")
    monkeypatch.setattr(urllib.request, "urlopen", _unexpected_request)

    # Act
    with pytest.raises(SystemExit) as error:
        alert.main()

    # Assert
    assert (
        str(error.value) == "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable main CI alerts."
    )


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (b'{"ok": false}', "Telegram rejected the CI alert."),
        (b"[]", "Telegram rejected the CI alert."),
        (b"not JSON", "Telegram request failed: JSONDecodeError."),
    ],
)
def test_alert_fails_when_telegram_does_not_confirm_delivery(
    event_path: Path, monkeypatch: pytest.MonkeyPatch, response: bytes, expected: str
) -> None:
    # Arrange
    _write_event(event_path)

    def reject(_request: urllib.request.Request, **_options: int) -> io.BytesIO:
        return io.BytesIO(response)

    monkeypatch.setattr(urllib.request, "urlopen", reject)

    # Act
    with pytest.raises(SystemExit) as error:
        alert.main()

    # Assert
    assert str(error.value) == expected


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            urllib.error.HTTPError(
                "https://api.telegram.org/bottest-token/sendMessage",
                403,
                "Forbidden",
                Message(),
                None,
            ),
            "Telegram returned HTTP 403.",
        ),
        (
            urllib.error.URLError("Timed out contacting bottest-token"),
            "Telegram request failed: URLError.",
        ),
    ],
)
def test_alert_reports_transport_errors_without_disclosing_the_bot_token(
    event_path: Path, monkeypatch: pytest.MonkeyPatch, failure: OSError, expected: str
) -> None:
    # Arrange
    _write_event(event_path)

    def fail(_request: urllib.request.Request, **_options: int) -> io.BytesIO:
        raise failure

    monkeypatch.setattr(urllib.request, "urlopen", fail)

    # Act
    with pytest.raises(SystemExit) as error:
        alert.main()

    # Assert
    assert str(error.value) == expected
