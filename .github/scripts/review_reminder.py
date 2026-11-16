import html
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

GITHUB_API = "https://api.github.com"
TELEGRAM_API = "https://api.telegram.org"
PAGE_SIZE = 100
TIMEOUT_SECONDS = 30
MESSAGE_LIMIT = 4096
VERDICTS = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    url: str
    author: str
    draft: bool
    waiting_since: datetime


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def is_reviewed(reviews: list[tuple[str, str]]) -> bool:
    latest = {reviewer: state for reviewer, state in reviews if state in VERDICTS}
    return not {"APPROVED", "CHANGES_REQUESTED"}.isdisjoint(latest.values())


def waiting(pulls: list[PullRequest], reviewed: set[int]) -> list[PullRequest]:
    return sorted(
        (pull for pull in pulls if not pull.draft and pull.number not in reviewed),
        key=lambda pull: pull.waiting_since,
    )


def format_wait(delta: timedelta) -> str:
    hours = max(int(delta.total_seconds() // 3600), 0)
    days, hours = divmod(hours, 24)
    return f"{days} d {hours} h" if days else f"{hours} h"


def _line(pull: PullRequest, now: datetime) -> tuple[str, str]:
    rest = f"{pull.title} by {pull.author}, waiting {format_wait(now - pull.waiting_since)}"
    return (
        f'<a href="{html.escape(pull.url)}">#{pull.number}</a> {html.escape(rest, quote=False)}',
        f"#{pull.number} {rest}",
    )


def visible_length(lines: list[tuple[str, str]]) -> int:
    """Telegram's length of the shown text, counted in UTF-16 code units."""
    text = "\n".join(shown for _, shown in lines)
    return len(text.encode("utf-16-le")) // 2


def build_message(pulls: list[PullRequest], now: datetime) -> str:
    """Lists the pull requests in order; those past Telegram's limit become an "and N more" line."""
    header = f"{len(pulls)} pull request(s) waiting for review"
    lines = [(f"<b>{header}</b>", header)]
    for index, pull in enumerate(pulls):
        hidden = len(pulls) - index - 1
        more = f"and {hidden} more"
        tail = [(more, more)] if hidden else []
        if visible_length([*lines, _line(pull, now), *tail]) > MESSAGE_LIMIT:
            more = f"and {hidden + 1} more"
            lines.append((more, more))
            break
        lines.append(_line(pull, now))
    return "\n".join(markup for markup, _ in lines)


def _request(request: urllib.request.Request) -> object:
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.load(response)


def _github(path: str, token: str) -> list[object]:
    items: list[object] = []
    page = 1
    while True:
        request = urllib.request.Request(
            f"{GITHUB_API}{path}?per_page={PAGE_SIZE}&page={page}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        match _request(request):
            case list(chunk):
                items.extend(chunk)
            case _:
                sys.exit(f"Unexpected response from GitHub for {path}")
        if len(chunk) < PAGE_SIZE:
            return items
        page += 1


def _pull_request(item: object, ready_at: datetime | None) -> PullRequest | None:
    match item:
        case {
            "number": int(number),
            "title": str(title),
            "html_url": str(url),
            "draft": bool(draft),
            "created_at": str(created_at),
            "user": {"login": str(author)},
        }:
            return PullRequest(
                number, title, url, author, draft, ready_at or parse_time(created_at)
            )
        case _:
            return None


def last_ready(events: list[object]) -> datetime | None:
    ready = [
        parse_time(created_at)
        for event in events
        if isinstance(event, dict)
        and event.get("event") == "ready_for_review"
        and isinstance(created_at := event.get("created_at"), str)
    ]
    return max(ready, default=None)


def _reviews(items: list[object]) -> list[tuple[str, str]]:
    reviews: list[tuple[str, str]] = []
    for item in items:
        match item:
            case {"state": str(state), "user": {"login": str(reviewer)}}:
                reviews.append((reviewer, state))
            case _:
                continue
    return reviews


def open_pull_requests(repository: str, token: str) -> tuple[list[PullRequest], set[int]]:
    pulls: list[PullRequest] = []
    reviewed: set[int] = set()
    for item in _github(f"/repos/{repository}/pulls", token):
        match item:
            case {"user": {"type": "Bot"}}:
                continue
            case {"number": int(number), "draft": False}:
                events = _github(f"/repos/{repository}/issues/{number}/events", token)
                pull = _pull_request(item, last_ready(events))
                if pull is None:
                    sys.exit(f"Unexpected pull request shape from GitHub for #{number}")
                reviews = _reviews(_github(f"/repos/{repository}/pulls/{number}/reviews", token))
                if is_reviewed(reviews):
                    reviewed.add(number)
                pulls.append(pull)
            case _:
                continue
    return pulls, reviewed


def send(text: str, bot_token: str, chat_id: str) -> None:
    body = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
    ).encode()
    request = urllib.request.Request(
        f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    _request(request)


def main() -> None:
    try:
        pulls, reviewed = open_pull_requests(
            os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
        )
        pending = waiting(pulls, reviewed)
        if not pending:
            sys.stdout.write("No pull request is waiting for review.\n")
            return
        send(
            build_message(pending, datetime.now(UTC)),
            os.environ["TELEGRAM_BOT_TOKEN"],
            os.environ["TELEGRAM_CHAT_ID"],
        )
    except urllib.error.HTTPError as error:
        sys.exit(f"HTTP {error.code} from {error.url.split('/bot')[0]}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        sys.exit(f"Request failed: {type(error).__name__}")
    sys.stdout.write(f"Reminded the team of {len(pending)} pull request(s).\n")


if __name__ == "__main__":
    main()
