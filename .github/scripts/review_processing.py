import hmac
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.client import HTTPException
from pathlib import Path
from typing import Self

API = "https://api.github.com"
CONTEXT = "Review processed"
MARKER = "<!-- whadio-review-processing -->"
PENDING_LABEL = "review-notification-pending"
PAGE_SIZE = 100
MIN_STATE_KEY_LENGTH = 32
VERDICTS = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
NIT = re.compile(r"^\s*nit:", re.IGNORECASE | re.MULTILINE)
REQUEST_ERRORS = (OSError, HTTPException, ValueError)


class RateLimitError(Exception):
    pass


@dataclass(frozen=True)
class Pull:
    number: int
    head: str
    author: str
    url: str
    node: str
    eligible: bool
    auto: bool
    release: bool = False

    @classmethod
    def parse(cls, item: object) -> Self:
        release = False
        match item:
            case {
                "user": {"login": "whadio-release-bot[bot]"},
                "head": {"ref": "chore/#275-release", "repo": {"full_name": str(head_repo)}},
                "base": {"repo": {"full_name": str(base_repo)}},
            }:
                release = head_repo == base_repo
        match item:
            case {
                "number": int(number),
                "head": {"sha": str(head)},
                "user": user,
                "html_url": str(url),
                "node_id": str(node),
                "state": str(state),
                "base": {"ref": str(base)},
                "auto_merge": auto,
                **extra,
            }:
                author = "deleted account"
                if isinstance(user, dict) and isinstance(user.get("login"), str):
                    author = user["login"]
                return cls(
                    number,
                    head,
                    author,
                    url,
                    node,
                    state == "open" and extra.get("draft") is False and base == "main",
                    auto is not None,
                    release,
                )
            case _:
                raise ValueError("Unexpected pull request response")


@dataclass(frozen=True)
class Review:
    id: int
    author: str | None
    state: str
    head: str | None
    body: str
    url: str

    @classmethod
    def parse(cls, item: object) -> Self:
        match item:
            case {
                "id": int(identity),
                "user": user,
                "state": str(state),
                "commit_id": (str() | None) as head,
                "body": str(body),
                "html_url": str(url),
            }:
                match user:
                    case {"login": str(author)}:
                        return cls(identity, author, state, head, body, url)
                    case None:
                        return cls(identity, None, state, head, body, url)
        raise ValueError("Unexpected review response")


@dataclass(frozen=True)
class Notification:
    id: int
    author: str
    url: str

    @classmethod
    def parse(cls, item: object) -> Self:
        match item:
            case {"id": int(identity), "author": str(author), "url": str(url)}:
                return cls(identity, author, url)
            case _:
                raise ValueError("Invalid pending review notification")


@dataclass
class Memory:
    comment: int | None = None
    manual: bool = False
    notified: set[int] = field(default_factory=set)
    pending: dict[int, Notification] = field(default_factory=dict)

    def body(self) -> str:
        return (
            f"{MARKER}\n"
            "Review processing state. Nits leave this PR for manual merging.\n"
            + json.dumps(
                {
                    "manual": self.manual,
                    "notified": sorted(self.notified),
                    "pending": [asdict(item) for item in self.pending.values()],
                }
            )
        )


class GitHub:
    def __init__(self, repository: str, token: str, *, state_key: str = "") -> None:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("Invalid repository")
        self.repository = repository
        self.token = token
        self.state_key = state_key

    def request(self, path: str, method: str = "GET", **payload: object) -> object:
        request = urllib.request.Request(
            f"{API}{path}",
            method=method,
            data=json.dumps(payload).encode() if payload else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == HTTPStatus.TOO_MANY_REQUESTS or (
                error.code == HTTPStatus.FORBIDDEN
                and (
                    error.headers.get("Retry-After") is not None
                    or error.headers.get("X-RateLimit-Remaining") == "0"
                )
            ):
                raise RateLimitError from None
            raise

    def repo(self, path: str, method: str = "GET", **payload: object) -> object:
        return self.request(f"/repos/{self.repository}{path}", method, **payload)

    def pages(self, path: str) -> list[object]:
        result: list[object] = []
        separator = "&" if "?" in path else "?"
        page = 1
        while True:
            match self.repo(f"{path}{separator}per_page=100&page={page}"):
                case list(items):
                    result.extend(items)
                case _:
                    raise ValueError("Unexpected paginated response")
            if len(items) < PAGE_SIZE:
                return result
            page += 1

    def pull(self, number: int) -> Pull:
        return Pull.parse(self.repo(f"/pulls/{number}"))

    def read_reviews(self, number: int) -> list[Review]:
        return [Review.parse(item) for item in self.pages(f"/pulls/{number}/reviews")]

    def open_numbers(self) -> set[int]:
        return pull_numbers(self.pages("/pulls?state=open&base=main"))

    def queued_pulls(self) -> set[int]:
        numbers: set[int] = set()
        for item in self.pages(f"/issues?state=all&labels={PENDING_LABEL}"):
            match item:
                case {"number": int(number), "pull_request": dict()}:
                    numbers.add(number)
        return numbers

    def queue(self, number: int) -> None:
        try:
            self.repo(f"/labels/{PENDING_LABEL}")
        except urllib.error.HTTPError as error:
            if error.code != HTTPStatus.NOT_FOUND:
                raise
            self.repo(
                "/labels",
                "POST",
                name=PENDING_LABEL,
                color="fbca04",
                description="Review processing has Telegram notifications to send",
            )
        self.repo(f"/issues/{number}/labels", "POST", labels=[PENDING_LABEL])

    def unqueue(self, number: int) -> None:
        try:
            self.repo(f"/issues/{number}/labels/{PENDING_LABEL}", "DELETE")
        except urllib.error.HTTPError as error:
            if error.code != HTTPStatus.NOT_FOUND:
                raise

    def status(self, pull: Pull, state: str, description: str) -> None:
        # Avoid creating a new status on every scheduled reconciliation.
        statuses = self.pages(f"/commits/{pull.head}/statuses")
        for status in statuses:
            match status:
                case {"context": str(context), "state": str(previous), **details} if (
                    context == CONTEXT
                ):
                    if previous == state and details.get("description") == description:
                        return
                    break
        self.repo(
            f"/statuses/{pull.head}", "POST", context=CONTEXT, state=state, description=description
        )

    def disable(self, pull: Pull) -> None:
        result = self.request(
            "/graphql",
            "POST",
            query="mutation($id: ID!) { disablePullRequestAutoMerge(input: "
            "{pullRequestId: $id}) { pullRequest { autoMergeRequest { enabledAt } } } }",
            variables={"id": pull.node},
        )
        match result:
            case {"errors": errors}:
                raise ValueError(f"Auto-merge cancellation failed: {errors}")
            case {
                "data": {
                    "disablePullRequestAutoMerge": {
                        "pullRequest": {"autoMergeRequest": None},
                    }
                }
            }:
                return
            case _:
                raise ValueError("Auto-merge cancellation was not confirmed")

    def remember(self, pull: Pull, memory: Memory) -> None:
        body = seal_state(memory.body(), self.state_key, self.repository, pull.number)
        if memory.comment is None:
            response = self.repo(f"/issues/{pull.number}/comments", "POST", body=body)
            match response:
                case {"id": int(identity)}:
                    memory.comment = identity
                case _:
                    raise ValueError("Could not save review state")
        else:
            self.repo(f"/issues/comments/{memory.comment}", "PATCH", body=body)

    def memory(self, pull: Pull) -> Memory:
        items = self.pages(f"/issues/{pull.number}/comments")
        return memory_from(items, self.state_key, self.repository, pull.number)


def pull_numbers(items: list[object]) -> set[int]:
    return {number for item in items if (number := pull_number(item)) is not None}


def pull_number(item: object) -> int | None:
    match item:
        case {"number": int(number)} if number > 0:
            return number
    return None


def state_signature(body: str, key: str, repository: str, number: int) -> str:
    return hmac.digest(key.encode(), f"{repository}:{number}\n{body}".encode(), "sha256").hex()


def seal_state(body: str, key: str, repository: str, number: int) -> str:
    return f"{body}\n<!-- {state_signature(body, key, repository, number)} -->"


def memory_from(items: list[object], key: str, repository: str, number: int) -> Memory:
    if not key:
        return Memory()
    for item in items:
        match item:
            case {
                "id": int(identity),
                "user": {"login": "github-actions[bot]"},
                "body": str(body),
            } if body.startswith(MARKER + "\n"):
                payload, _, signature = body.rpartition("\n")
                expected = f"<!-- {state_signature(payload, key, repository, number)} -->"
                if not hmac.compare_digest(signature.encode(), expected.encode()):
                    continue
                match json.loads(payload.splitlines()[-1]):
                    case {"manual": bool(manual), "notified": list(notified), **remaining}:
                        pending = remaining.get("pending", [])
                        if isinstance(pending, list) and all(
                            isinstance(value, int) for value in notified
                        ):
                            notices = [Notification.parse(item) for item in pending]
                            return Memory(
                                identity,
                                manual,
                                set(notified),
                                {item.id: item for item in notices if item.id not in notified},
                            )
                raise ValueError("Invalid saved review state")
    return Memory()


def inline_nit_ids(comments: list[object]) -> set[int]:
    inline: set[int] = set()
    for comment in comments:
        match comment:
            case {"pull_request_review_id": int(identity), "body": str(body)}:
                if NIT.search(body):
                    inline.add(identity)
    return inline


def review_snapshot(github: GitHub, number: int) -> tuple[list[Review], set[int]] | None:
    reviews = github.read_reviews(number)
    # A submission may become visible between the two REST endpoints' responses.
    for _ in range(2):
        inline = inline_nit_ids(github.pages(f"/pulls/{number}/comments"))
        latest = github.read_reviews(number)
        if latest == reviews and inline.issubset(review.id for review in reviews):
            return reviews, inline
        reviews = latest
    return None


def nit_reviews(reviews: list[Review], inline: set[int]) -> list[Review]:
    return [
        review
        for review in reviews
        if review.state == "APPROVED" and (review.id in inline or NIT.search(review.body))
    ]


def approved(pull: Pull, reviews: list[Review]) -> bool:
    latest: dict[str, Review] = {}
    for review in sorted(reviews, key=lambda item: item.id):
        if review.author is not None and review.state in VERDICTS:
            latest[review.author] = review
    return not any(review.state == "CHANGES_REQUESTED" for review in latest.values()) and any(
        review.state == "APPROVED" and review.head == pull.head and review.author != pull.author
        for review in latest.values()
    )


def notify(pull: Pull, review: Notification) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        raise ValueError("Telegram token and chat ID must both be configured")
    text = (
        f'<a href="{html.escape(pull.url, quote=True)}">PR #{pull.number}</a> '
        f"by {html.escape(pull.author)} approved with nits by {html.escape(review.author)}.\n"
        "This review left the PR for manual merging.\n"
        f'<a href="{html.escape(review.url, quote=True)}">Review</a>'
    )
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(
            {
                "chat_id": chat,
                "text": text,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        match json.load(response):
            case {"ok": True}:
                return
            case _:
                raise ValueError("Telegram did not confirm delivery")


def eligible_reviews(github: GitHub, reviews: list[Review]) -> list[Review]:
    allowed: set[str] = set()
    reviewers = {
        review.author
        for review in reviews
        if review.author is not None and review.state in VERDICTS
    }
    for reviewer in reviewers:
        match github.repo(f"/collaborators/{reviewer}/permission"):
            case {"permission": "admin" | "maintain" | "write"}:
                allowed.add(reviewer)
    return [review for review in reviews if review.author in allowed]


def deliver(github: GitHub, pull: Pull, memory: Memory) -> bool:
    if memory.comment is None:
        raise ValueError("Queued notification has no authenticated state")
    delivery_ok = True
    for review in list(memory.pending.values()):
        try:
            notify(pull, review)
        except REQUEST_ERRORS:
            sys.stderr.write(
                f"Telegram delivery failed for PR #{pull.number}, review {review.id}\n"
            )
            delivery_ok = False
        else:
            memory.notified.add(review.id)
            del memory.pending[review.id]
            github.remember(pull, memory)
    if not memory.pending:
        github.unqueue(pull.number)
    return delivery_ok


def retry_delivery(github: GitHub, pull: Pull, *, queued: bool) -> bool:
    if not queued:
        return True
    return deliver(github, pull, github.memory(pull))


def save_notifications(
    github: GitHub,
    pull: Pull,
    memory: Memory,
    notices: dict[int, Notification],
    *,
    queued: bool,
) -> bool:
    # Apply the label before saving state so the queue can find the notification after a restart.
    if (notices or memory.pending) and not queued:
        github.queue(pull.number)
        queued = True
    if notices:
        memory.manual = True
        memory.pending.update(notices)
        github.remember(pull, memory)
    return queued


def release_gate(
    github: GitHub, pull: Pull, snapshot: tuple[list[Review], set[int]], *, manual: bool
) -> None:
    if review_snapshot(github, pull.number) != snapshot:
        github.status(pull, "pending", "Reviews changed during inspection; waiting to retry")
        return
    # Check the head and auto-merge again after the review and queue API calls.
    current = github.pull(pull.number)
    if current.head != pull.head or not current.eligible:
        return
    if manual and current.auto:
        raise ValueError("Auto-merge was re-enabled during review processing")
    github.status(
        current,
        "success",
        "Review processed; manual merge" if manual else "Clean current-head approval processed",
    )


def process(github: GitHub, number: int, *, queued: bool = False) -> bool:
    pull = github.pull(number)
    if not pull.eligible or pull.release:
        return retry_delivery(github, pull, queued=queued)
    snapshot = review_snapshot(github, number)
    if snapshot is None:
        github.status(
            pull,
            "pending",
            "Reviews changed during inspection; waiting to retry",
        )
        return retry_delivery(github, pull, queued=queued)
    all_reviews, inline = snapshot
    reviews = eligible_reviews(github, all_reviews)
    nits = nit_reviews(reviews, inline)
    memory = github.memory(pull)
    manual = memory.manual or bool(nits)
    ready = approved(pull, reviews)
    if queued and memory.comment is None and not nits:
        github.status(pull, "pending", "Queued notification state could not be verified")
        raise ValueError("Queued notification has no authenticated state")
    new_notices = {
        review.id: Notification(review.id, review.author, review.url)
        for review in nits
        if review.author is not None
        and review.id not in memory.notified
        and review.id not in memory.pending
    }
    if not ready or (manual and pull.auto) or new_notices:
        github.status(
            pull,
            "pending",
            "Inspecting current-head approval",
        )
    if manual and pull.auto:
        github.disable(pull)
    queued = save_notifications(github, pull, memory, new_notices, queued=queued)
    if ready:
        release_gate(github, pull, snapshot, manual=manual)
    return deliver(github, pull, memory) if queued else True


def reconcile(github: GitHub, *, targets: set[int] | None = None) -> int:
    failures = 0
    queued: set[int] = set()
    try:
        queued = github.queued_pulls()
    except REQUEST_ERRORS:
        sys.stderr.write("Unable to read the notification queue\n")
        failures += 1
    if targets is not None:
        queued &= targets
    try:
        numbers = github.open_numbers() if targets is None else targets
    except REQUEST_ERRORS:
        sys.stderr.write("Unable to list open pull requests\n")
        numbers = set()
        failures += 1
    for number in sorted(numbers | queued):
        try:
            if number in numbers:
                ok = process(github, number, queued=number in queued)
            else:
                ok = retry_delivery(github, github.pull(number), queued=True)
            if not ok:
                failures += 1
        except REQUEST_ERRORS:
            # HTTP errors can contain Telegram tokens in their URL; do not print them.
            sys.stderr.write(f"Review processing failed for PR #{number}\n")
            failures += 1
    return failures


def event_targets(name: str, event: object) -> set[int] | None:
    match name, event:
        case "pull_request_target", {"pull_request": pull}:
            return pull_numbers([pull])
        case "workflow_run", {"workflow_run": {"pull_requests": list(items)}}:
            return pull_numbers(items)
        case "workflow_dispatch", {"inputs": {"pull_request": value}} if value:
            return {positive_number(value)}
        case "schedule" | "workflow_dispatch", _:
            return None
        case _:
            return set()


def positive_number(value: object) -> int:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        number = int(value)
        if number > 0:
            return number
    raise ValueError("Expected a positive pull request number")


def main() -> None:
    state_key = os.environ.get("REVIEW_PROCESSING_STATE_KEY", "")
    if len(state_key) < MIN_STATE_KEY_LENGTH:
        sys.exit("Configure a random REVIEW_PROCESSING_STATE_KEY of at least 32 characters")
    github = GitHub(
        os.environ["GITHUB_REPOSITORY"],
        os.environ["GITHUB_TOKEN"],
        state_key=state_key,
    )
    try:
        event: object = json.loads(
            Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
        )
        targets = event_targets(os.environ["GITHUB_EVENT_NAME"], event)
        test_pr = os.environ.get("REVIEW_PROCESSING_TEST_PR", "")
        if test_pr:
            trial = {positive_number(test_pr)}
            targets = trial if targets is None else targets & trial
        if targets == set():
            return
        failures = reconcile(github, targets=targets)
    except RateLimitError:
        sys.exit("GitHub API rate limit reached; reconciliation will retry on a later run")
    except REQUEST_ERRORS:
        sys.exit("Unable to start review reconciliation; check the event data and GitHub API")
    if failures:
        sys.exit(f"{failures} PR(s) need a retry; see the processing and delivery errors above")


if __name__ == "__main__":
    main()
