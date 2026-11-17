import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Self

API = "https://api.github.com"
CONTEXT = "Review processed"
MARKER = "<!-- whadio-review-processing -->"
PAGE_SIZE = 100
NIT = re.compile(r"^\s*nit:", re.IGNORECASE | re.MULTILINE)


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
                "user": {"login": str(author)},
                "html_url": str(url),
                "node_id": str(node),
                "state": str(state),
                "draft": bool(draft),
                "base": {"ref": str(base)},
                "auto_merge": auto,
            }:
                return cls(
                    number,
                    head,
                    author,
                    url,
                    node,
                    state == "open" and not draft and base == "main",
                    auto is not None,
                    release,
                )
            case _:
                raise ValueError("Unexpected pull request response")


@dataclass(frozen=True)
class Review:
    id: int
    author: str
    state: str
    head: str
    body: str
    url: str

    @classmethod
    def parse(cls, item: object) -> Self:
        match item:
            case {
                "id": int(identity),
                "user": {"login": str(author)},
                "state": str(state),
                "commit_id": str(head),
                "body": str(body),
                "html_url": str(url),
            }:
                return cls(identity, author, state, head, body, url)
            case _:
                raise ValueError("Unexpected review response")


@dataclass
class Memory:
    comment: int | None = None
    manual: bool = False
    notified: set[int] = field(default_factory=set)


class GitHub:
    def __init__(self, repository: str, token: str) -> None:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("Invalid repository")
        self.repository = repository
        self.token = token

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
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

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

    def status(self, pull: Pull, state: str, description: str) -> None:
        # Avoid creating a new status on every scheduled reconciliation.
        statuses = self.pages(f"/commits/{pull.head}/statuses")
        for status in statuses:
            match status:
                case {"context": str(context), "state": str(previous)} if context == CONTEXT:
                    if previous == state:
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
        body = (
            f"{MARKER}\n"
            "Review processing state. Nits leave this PR for manual merging.\n"
            + json.dumps({"manual": memory.manual, "notified": sorted(memory.notified)})
        )
        if memory.comment is None:
            response = self.repo(f"/issues/{pull.number}/comments", "POST", body=body)
            match response:
                case {"id": int(identity)}:
                    memory.comment = identity
                case _:
                    raise ValueError("Could not save review state")
        else:
            self.repo(f"/issues/comments/{memory.comment}", "PATCH", body=body)


def memory_from(items: list[object]) -> Memory:
    for item in items:
        match item:
            case {
                "id": int(identity),
                "user": {"login": "github-actions[bot]"},
                "body": str(body),
            } if body.startswith(MARKER + "\n"):
                match json.loads(body.splitlines()[-1]):
                    case {"manual": bool(manual), "notified": list(notified)}:
                        if all(isinstance(value, int) for value in notified):
                            return Memory(identity, manual, set(notified))
                raise ValueError("Invalid saved review state")
    return Memory()


def nit_reviews(reviews: list[Review], comments: list[object]) -> list[Review]:
    inline: set[int] = set()
    for comment in comments:
        match comment:
            case {"pull_request_review_id": int(identity), "body": str(body)}:
                if NIT.search(body):
                    inline.add(identity)
    return [
        review
        for review in reviews
        if review.state == "APPROVED" and (review.id in inline or NIT.search(review.body))
    ]


def approved(pull: Pull, reviews: list[Review]) -> bool:
    latest: dict[str, Review] = {}
    for review in sorted(reviews, key=lambda item: item.id):
        if review.state in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest[review.author] = review
    return not any(review.state == "CHANGES_REQUESTED" for review in latest.values()) and any(
        review.state == "APPROVED" and review.head == pull.head and review.author != pull.author
        for review in latest.values()
    )


def notify(pull: Pull, review: Review) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        raise ValueError("Telegram token and chat ID must both be configured")
    text = (
        f'<a href="{html.escape(pull.url, quote=True)}">PR #{pull.number}</a> '
        f"by {html.escape(pull.author)} approved with nits by {html.escape(review.author)}.\n"
        "Auto-merge is disabled. The author may address the nits or merge manually.\n"
        f'<a href="{html.escape(review.url, quote=True)}">Review and comments</a>'
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
    with urllib.request.urlopen(request, timeout=30) as response:
        match json.load(response):
            case {"ok": True}:
                return
            case _:
                raise ValueError("Telegram did not confirm delivery")


def eligible_reviews(github: GitHub, reviews: list[Review]) -> list[Review]:
    allowed: set[str] = set()
    for reviewer in {review.author for review in reviews}:
        match github.repo(f"/collaborators/{reviewer}/permission"):
            case {"permission": "admin" | "maintain" | "write"}:
                allowed.add(reviewer)
    return [review for review in reviews if review.author in allowed]


def deliver(github: GitHub, pull: Pull, memory: Memory, nits: list[Review]) -> bool:
    delivery_ok = True
    for review in nits:
        if review.id in memory.notified:
            continue
        try:
            notify(pull, review)
        except (urllib.error.URLError, ValueError, TimeoutError):
            sys.stderr.write(
                f"Telegram delivery failed for PR #{pull.number}, review {review.id}\n"
            )
            delivery_ok = False
        else:
            memory.notified.add(review.id)
            github.remember(pull, memory)
    return delivery_ok


def process(github: GitHub, number: int, *, enabled: bool) -> bool:
    pull = github.pull(number)
    if not pull.eligible or pull.release:
        return True
    reviews = eligible_reviews(
        github, [Review.parse(item) for item in github.pages(f"/pulls/{number}/reviews")]
    )
    nits = nit_reviews(reviews, github.pages(f"/pulls/{number}/comments"))
    memory = memory_from(github.pages(f"/issues/{number}/comments"))
    manual = memory.manual or bool(nits)
    ready = approved(pull, reviews)
    if not enabled:
        sys.stdout.write(
            f"Dry run #{number}: approved={ready}, manual={manual}, auto={pull.auto}\n"
        )
        return True
    revoke = manual or (
        not ready
        and any(
            review.state
            in {
                "APPROVED",
                "CHANGES_REQUESTED",
                "DISMISSED",
            }
            for review in reviews
        )
    )
    if not ready or (revoke and pull.auto):
        github.status(pull, "pending", "Inspecting current-head approval")
    if revoke and pull.auto:
        github.disable(pull)
    if manual and not memory.manual:
        memory.manual = True
        github.remember(pull, memory)
    # A changed head must never inherit a decision about the previous commit.
    current = github.pull(number)
    if current.head != pull.head or not current.eligible:
        return True
    if revoke and current.auto:
        raise ValueError("Auto-merge was re-enabled during review processing")
    if ready:
        github.status(
            pull,
            "success",
            "Review processed; manual merge" if manual else "Clean current-head approval processed",
        )
    return deliver(github, pull, memory, nits)


def main() -> None:
    github = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
    enabled = os.environ.get("REVIEW_PROCESSING_ENABLED") == "true"
    failures = 0
    for item in github.pages("/pulls?state=open&base=main"):
        pull = Pull.parse(item)
        try:
            if not process(github, pull.number, enabled=enabled):
                failures += 1
        except (urllib.error.URLError, ValueError, TimeoutError):
            # HTTP errors can contain Telegram tokens in their URL; do not print them.
            sys.stderr.write(f"Review processing failed for PR #{pull.number}; gate not released\n")
            failures += 1
    if failures:
        sys.exit(f"{failures} PR(s) need a retry; see the processing and delivery errors above")


if __name__ == "__main__":
    main()
