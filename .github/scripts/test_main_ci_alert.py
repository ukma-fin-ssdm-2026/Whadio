import io
import json
import runpy
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

import pytest
import yaml

REPOSITORY_URL = "https://github.com/org/repo"
COMMIT = "ae00e35938fadd6b14db07482758ecd008f2fde7"
RUN_ID = "40963978557"


@pytest.fixture
def release_workflow() -> object:
    release = Path(__file__).parents[1] / "workflows" / "release.yml"
    return yaml.safe_load(release.read_text(encoding="utf-8"))


@pytest.fixture
def alert_job(release_workflow: object) -> object:
    match release_workflow:
        case {"jobs": {"notify-main-failure": job}}:
            return job
        case _:
            pytest.fail("The main CI alert job is missing from the Release workflow.")


@pytest.fixture
def alert_step(alert_job: object) -> object:
    match alert_job:
        case {"steps": [step]}:
            return step
        case _:
            pytest.fail("Expected the main CI alert job to contain one sender step.")


@pytest.fixture
def sender_script(alert_step: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    match alert_step:
        case {"run": str(command)}:
            header, *source, delimiter = command.splitlines()
            assert header == "python3 -I - <<'PY'"
            assert delimiter == "PY"
        case _:
            pytest.fail("The Telegram sender step is missing from the Release workflow.")

    script = tmp_path / "sender.py"
    script.write_text("\n".join(source) + "\n", encoding="utf-8")
    for name, value in {
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "org/repo",
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_CHAT_ID": "42",
        "FAILED_HEAD_SHA": COMMIT,
        "FAILED_RUN_ID": RUN_ID,
        "FAILED_RUN_ATTEMPT": "1",
    }.items():
        monkeypatch.setenv(name, value)
    return script


def test_release_listens_for_completed_ci_runs(release_workflow: object) -> None:
    # Arrange
    expected = {"workflows": ["CI/CD"], "types": ["completed"]}

    # Act
    # PyYAML interprets an unquoted `on` key as the YAML 1.1 boolean true.
    match release_workflow:
        case {"on": {"workflow_run": trigger}} | {True: {"workflow_run": trigger}}:
            actual = trigger
        case _:
            pytest.fail("The Release workflow is missing its CI completion trigger.")

    # Assert
    assert actual == expected


def test_alert_job_only_runs_for_failed_main_ci_in_this_repository(alert_job: object) -> None:
    # Arrange
    expected = (
        "github.event_name == 'workflow_run'"
        " && github.event.workflow_run.conclusion == 'failure'"
        " && github.event.workflow_run.head_branch == 'main'"
        " && github.event.workflow_run.head_repository.full_name == github.repository"
        " && (github.event.workflow_run.event == 'push'"
        " || github.event.workflow_run.event == 'workflow_dispatch')"
    )

    # Act
    match alert_job:
        case {"if": str(condition)}:
            actual = " ".join(condition.split())
        case _:
            pytest.fail("The main CI alert job has no condition.")

    # Assert
    assert actual == expected


def test_alert_step_gets_run_fields_and_telegram_secrets_from_github(alert_step: object) -> None:
    # Arrange
    expected = {
        "FAILED_RUN_ID": "${{ github.event.workflow_run.id }}",
        "FAILED_RUN_ATTEMPT": "${{ github.event.workflow_run.run_attempt }}",
        "FAILED_HEAD_SHA": "${{ github.event.workflow_run.head_sha }}",
        "TELEGRAM_BOT_TOKEN": "${{ secrets.TELEGRAM_BOT_TOKEN }}",
        "TELEGRAM_CHAT_ID": "${{ secrets.TELEGRAM_CHAT_ID }}",
    }

    # Act
    match alert_step:
        case {"env": bindings}:
            actual = bindings
        case _:
            pytest.fail("The main CI alert step has no environment bindings.")

    # Assert
    assert actual == expected


@pytest.mark.parametrize("attempt", ["1", "2"])
def test_alert_links_to_the_commit_and_exact_failed_attempt(
    sender_script: Path, monkeypatch: pytest.MonkeyPatch, attempt: str
) -> None:
    # Arrange
    sent: list[tuple[str, str, int, object]] = []

    def deliver(request: urllib.request.Request, *, timeout: int) -> io.BytesIO:
        assert isinstance(request.data, bytes)
        sent.append((request.get_method(), request.full_url, timeout, json.loads(request.data)))
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setenv("FAILED_RUN_ATTEMPT", attempt)
    monkeypatch.setattr(urllib.request, "urlopen", deliver)

    # Act
    runpy.run_path(str(sender_script))

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


@pytest.mark.parametrize("secret", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
def test_alert_stops_before_contacting_telegram_when_a_secret_is_empty(
    sender_script: Path, monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    # Arrange
    def unexpected_request(_request: urllib.request.Request, **_options: int) -> io.BytesIO:
        pytest.fail("Missing secrets should stop the sender before any HTTP request.")

    monkeypatch.setenv(secret, "")
    monkeypatch.setattr(urllib.request, "urlopen", unexpected_request)

    # Act
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(sender_script))

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
    sender_script: Path, monkeypatch: pytest.MonkeyPatch, response: bytes, expected: str
) -> None:
    # Arrange
    def reject(_request: urllib.request.Request, **_options: int) -> io.BytesIO:
        return io.BytesIO(response)

    monkeypatch.setattr(urllib.request, "urlopen", reject)

    # Act
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(sender_script))

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
    sender_script: Path, monkeypatch: pytest.MonkeyPatch, failure: OSError, expected: str
) -> None:
    # Arrange
    def fail(_request: urllib.request.Request, **_options: int) -> io.BytesIO:
        raise failure

    monkeypatch.setattr(urllib.request, "urlopen", fail)

    # Act
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(sender_script))

    # Assert
    assert str(error.value) == expected
