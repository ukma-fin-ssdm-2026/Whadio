import html
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

GITHUB_API = "https://api.github.com"
TELEGRAM_API = "https://api.telegram.org"
PAGE_SIZE = 100
TIMEOUT_SECONDS = 30
MESSAGE_LIMIT = 4096
NOT_REVIEWED = "Not reviewed yet"
RE_REVIEW = "Waiting for a re-review"
FIXES = "Waiting for fixes"
SECTIONS = (NOT_REVIEWED, RE_REVIEW, FIXES)


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    url: str
    author: str
    ready_at: datetime
    pushed_at: datetime
    verdicts: dict[str, tuple[str, datetime]]


@dataclass(frozen=True)
class Entry:
    pull: PullRequest
    section: str
    names: str
    since: datetime


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def classify(pull: PullRequest) -> Entry | None:
    """Sorts a pull request by whom it waits for; approvals stand through pushes."""
    changes = {
        reviewer: submitted_at
        for reviewer, (state, submitted_at) in pull.verdicts.items()
        if state == "CHANGES_REQUESTED"
    }
    if any(submitted_at > pull.pushed_at for submitted_at in changes.values()):
        return Entry(pull, FIXES, pull.author, max(changes.values()))
    if changes:
        return Entry(pull, RE_REVIEW, ", ".join(sorted(changes)), pull.pushed_at)
    if not pull.verdicts:
        return Entry(pull, NOT_REVIEWED, pull.author, pull.ready_at)
    return None


def waiting(pulls: list[PullRequest]) -> list[Entry]:
    return sorted(
        (entry for pull in pulls if (entry := classify(pull)) is not None),
        key=lambda entry: (SECTIONS.index(entry.section), entry.since),
    )


def format_wait(delta: timedelta) -> str:
    hours = max(int(delta.total_seconds() // 3600), 0)
    days, hours = divmod(hours, 24)
    return f"{days} d {hours} h" if days else f"{hours} h"


def _line(entry: Entry, now: datetime) -> tuple[str, str]:
    reviewers = f", re-review from {entry.names}" if entry.section == RE_REVIEW else ""
    rest = (
        f"{entry.pull.title} by {entry.pull.author}{reviewers}, "
        f"waiting {format_wait(now - entry.since)}"
    )
    link = f'<a href="{html.escape(entry.pull.url)}">#{entry.pull.number}</a>'
    return f"{link} {html.escape(rest, quote=False)}", f"#{entry.pull.number} {rest}"


def visible_length(lines: list[tuple[str, str]]) -> int:
    """Telegram's length of the shown text, counted in UTF-16 code units."""
    text = "\n".join(shown for _, shown in lines)
    return len(text.encode("utf-16-le")) // 2


def build_message(entries: list[Entry], now: datetime) -> str:
    """Lists entries under a header per section; those past Telegram's limit become "and N more"."""
    counts = Counter(entry.section for entry in entries)
    lines: list[tuple[str, str]] = []
    previous = None
    for index, entry in enumerate(entries):
        hidden = len(entries) - index - 1
        more = f"and {hidden} more"
        tail = [(more, more)] if hidden else []
        block = [_line(entry, now)]
        if entry.section != previous:
            title = f"{entry.section} ({counts[entry.section]})"
            block = [*([("", "")] if lines else []), (f"<b>{title}</b>", title), *block]
        if visible_length([*lines, *block, *tail]) > MESSAGE_LIMIT:
            more = f"and {hidden + 1} more"
            lines.append((more, more))
            break
        lines.extend(block)
        previous = entry.section
    return "\n".join(markup for markup, _ in lines)


def _request(request: urllib.request.Request) -> object:
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.load(response)


def _authorized(url: str, token: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def _github(path: str, token: str) -> list[object]:
    items: list[object] = []
    page = 1
    while True:
        request = _authorized(f"{GITHUB_API}{path}?per_page={PAGE_SIZE}&page={page}", token)
        match _request(request):
            case list(chunk):
                items.extend(chunk)
            case _:
                sys.exit(f"Unexpected response from GitHub for {path}")
        if len(chunk) < PAGE_SIZE:
            return items
        page += 1


def _pull_request(
    item: object,
    ready_at: datetime | None,
    pushed_at: datetime,
    verdicts: dict[str, tuple[str, datetime]],
) -> PullRequest | None:
    match item:
        case {
            "number": int(number),
            "title": str(title),
            "html_url": str(url),
            "created_at": str(created_at),
            "user": {"login": str(author)},
        }:
            return PullRequest(
                number, title, url, author, ready_at or parse_time(created_at), pushed_at, verdicts
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


def standing_verdicts(reviews: list[object]) -> dict[str, tuple[str, datetime]]:
    """Each reviewer's latest approval or change request; a dismissal withdraws it."""
    verdicts: dict[str, tuple[str, datetime]] = {}
    for review in reviews:
        match review:
            case {
                "state": "DISMISSED",
                "user": {"login": str(reviewer)},
            }:
                verdicts.pop(reviewer, None)
            case {
                "state": str(state),
                "user": {"login": str(reviewer)},
                "submitted_at": str(submitted_at),
            } if state in {"APPROVED", "CHANGES_REQUESTED"}:
                verdicts[reviewer] = (state, parse_time(submitted_at))
            case _:
                continue
    return verdicts


def open_pull_requests(repository: str, token: str) -> list[PullRequest]:
    pulls: list[PullRequest] = []
    for item in _github(f"/repos/{repository}/pulls", token):
        match item:
            case {"user": {"type": "Bot"}}:
                continue
            case {"number": int(number), "draft": False, "head": {"sha": str(sha)}}:
                events = _github(f"/repos/{repository}/issues/{number}/events", token)
                match _request(
                    _authorized(f"{GITHUB_API}/repos/{repository}/commits/{sha}", token)
                ):
                    case {"commit": {"committer": {"date": str(date)}}}:
                        pushed_at = parse_time(date)
                    case _:
                        sys.exit(f"Unexpected commit shape from GitHub for #{number}")
                verdicts = standing_verdicts(
                    _github(f"/repos/{repository}/pulls/{number}/reviews", token)
                )
                pull = _pull_request(item, last_ready(events), pushed_at, verdicts)
                if pull is None:
                    sys.exit(f"Unexpected pull request shape from GitHub for #{number}")
                pulls.append(pull)
            case _:
                continue
    return pulls


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
        pending = waiting(
            open_pull_requests(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
        )
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
