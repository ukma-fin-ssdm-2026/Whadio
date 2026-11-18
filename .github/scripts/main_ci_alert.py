import html
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkflowRun:
    run_id: int | None
    attempt: int | None
    sha: str | None
    conclusion: str
    branch: str
    repository: str
    trigger: str


def workflow_run(event: object) -> WorkflowRun | None:
    match event:
        case {
            "workflow_run": {
                "id": (int() | None) as run_id,
                "run_attempt": (int() | None) as attempt,
                "head_sha": (str() | None) as sha,
                "conclusion": str(conclusion),
                "head_branch": str(branch),
                "head_repository": {"full_name": str(repository)},
                "event": str(trigger),
            },
        }:
            return WorkflowRun(run_id, attempt, sha, conclusion, branch, repository, trigger)
        case _:
            return None


def should_alert(run: WorkflowRun, repository: str) -> bool:
    return (
        run.conclusion == "failure"
        and run.branch == "main"
        and run.repository == repository
        and run.trigger in {"push", "workflow_dispatch"}
    )


def failed_main_attempt(event: object, repository: str) -> tuple[int, int, str] | None:
    run = workflow_run(event)
    if run is None or not should_alert(run, repository):
        return None
    if run.run_id is None or run.attempt is None or run.sha is None:
        sys.exit("GitHub event is missing failed run metadata.")
    return run.run_id, run.attempt, run.sha


def main() -> None:
    try:
        with Path(os.environ["GITHUB_EVENT_PATH"]).open(encoding="utf-8") as event_file:
            event: object = json.load(event_file)
    except (OSError, ValueError) as error:
        sys.exit(f"Could not read the GitHub event: {type(error).__name__}.")

    repository = os.environ["GITHUB_REPOSITORY"]
    run = failed_main_attempt(event, repository)
    if run is None:
        return

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        sys.exit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable main CI alerts.")

    run_id, attempt, sha = run
    repository_url = f"{os.environ['GITHUB_SERVER_URL']}/{repository}"
    commit_url = f"{repository_url}/commit/{sha}"
    run_url = f"{repository_url}/actions/runs/{run_id}/attempts/{attempt}"
    text = (
        "🔴 Whadio CI/CD failed on main\n"
        f'Commit <a href="{html.escape(commit_url)}">{html.escape(sha[:7])}</a>\n'
        f'<a href="{html.escape(run_url)}">View failed CI run (attempt {attempt})</a>'
    )

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result: object = json.load(response)
    except urllib.error.HTTPError as error:
        sys.exit(f"Telegram returned HTTP {error.code}.")
    except (OSError, ValueError) as error:
        sys.exit(f"Telegram request failed: {type(error).__name__}.")
    match result:
        case {"ok": True}:
            return
    sys.exit("Telegram rejected the CI alert.")


if __name__ == "__main__":
    main()
