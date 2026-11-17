import importlib.util
import json
import urllib.request
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import ModuleType
from typing import Protocol

import pytest


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "review_processing",
        Path(__file__).with_name("review_processing.py"),
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


processor = _load()


def _review(
    identity: int = 1,
    *,
    state: str = "APPROVED",
    head: str = "head",
    author: str = "reviewer",
    body: str = "Looks good",
) -> object:
    return {
        "id": identity,
        "user": {"login": author},
        "state": state,
        "commit_id": head,
        "body": body,
        "html_url": "https://github.com/o/r/pull/1#review",
    }


class IMemory(Protocol):
    manual: bool
    notified: set[int]


class FakeGitHub:
    def __init__(self) -> None:
        self.current = processor.Pull(
            1,
            "head",
            "author",
            "https://github.com/o/r/pull/1",
            "PR_node",
            eligible=True,
            auto=True,
        )
        self.reviews: list[object] = []
        self.comments: list[object] = []
        self.memory: list[object] = []
        self.events: list[str] = []
        self.permission = "write"
        self.cancel_fails = False
        self.new_head = False
        self.reads = 0

    def pull(self, _number: int) -> object:
        self.reads += 1
        if self.new_head and self.reads > 1:
            return replace(self.current, head="new-head")
        return self.current

    def pages(self, path: str) -> list[object]:
        if path.endswith("/reviews"):
            return self.reviews
        if path == "/pulls/1/comments":
            return self.comments
        return self.memory

    def repo(self, _path: str) -> object:
        return {"permission": self.permission}

    def status(self, _pull: object, state: str, _description: str) -> None:
        self.events.append(state)

    def disable(self, _pull: object) -> None:
        self.events.append("disable")
        if self.cancel_fails:
            raise ValueError("Cancellation failed")
        self.current = replace(self.current, auto=False)

    def remember(self, _pull: object, memory: IMemory) -> None:
        self.events.append("remember")
        self.memory = [
            {
                "id": 10,
                "user": {"login": "github-actions[bot]"},
                "body": processor.MARKER
                + "\n"
                + json.dumps(
                    {
                        "manual": memory.manual,
                        "notified": sorted(memory.notified),
                    }
                ),
            }
        ]


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    fake = FakeGitHub()
    monkeypatch.setattr(processor, "notify", lambda *_: fake.events.append("notify"))
    return fake


def test_clean_approval_leaves_authors_auto_merge_enabled(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review()]
    # Act
    processor.process(github, 1, enabled=True)
    # Assert
    assert github.events == ["success"]


def test_waiting_for_first_approval_keeps_auto_merge_enabled(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = []
    # Act
    processor.process(github, 1, enabled=True)
    # Assert
    assert github.events == ["pending"]


def test_nit_disables_before_releasing_gate_and_notifying(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename this")]
    # Act
    processor.process(github, 1, enabled=True)
    # Assert
    assert github.events == ["pending", "disable", "remember", "success", "notify", "remember"]


def test_manual_merge_with_nits_is_allowed_after_processing(github: FakeGitHub) -> None:
    # Arrange
    github.current = replace(github.current, auto=False)
    github.reviews = [_review(body="Nit: rename this")]
    # Act
    processor.process(github, 1, enabled=True)
    # Assert
    assert github.events == ["remember", "success", "notify", "remember"]


def test_failed_cancellation_never_releases_gate(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename this")]
    github.cancel_fails = True
    # Act
    with pytest.raises(ValueError, match="Cancellation failed"):
        processor.process(github, 1, enabled=True)
    # Assert
    assert github.events == ["pending", "disable"]


def test_new_head_during_processing_is_not_released(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review()]
    github.new_head = True
    # Act
    processor.process(github, 1, enabled=True)
    # Assert
    assert "success" not in github.events


@pytest.mark.parametrize(
    "review",
    [
        _review(head="old"),
        _review(state="DISMISSED"),
        _review(state="CHANGES_REQUESTED"),
        _review(author="author"),
    ],
)
def test_invalid_approval_does_not_release_gate(github: FakeGitHub, review: object) -> None:
    # Arrange
    github.reviews = [review]
    # Act
    processor.process(github, 1, enabled=True)
    # Assert
    assert "success" not in github.events


def test_reader_approval_does_not_release_gate(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review()]
    github.permission = "read"
    # Act
    processor.process(github, 1, enabled=True)
    # Assert
    assert "success" not in github.events


def test_outsider_verdict_does_not_override_teammate(
    github: FakeGitHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    github.reviews = [_review(), _review(2, author="outsider", state="CHANGES_REQUESTED")]

    def repo(path: str) -> object:
        return {"permission": "read" if "outsider" in path else "write"}

    monkeypatch.setattr(github, "repo", repo)
    # Act
    processor.process(github, 1, enabled=True)
    # Assert
    assert github.events == ["success"]


def test_reenabling_during_cancellation_keeps_gate_blocked(
    github: FakeGitHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename")]
    monkeypatch.setattr(github, "disable", lambda _pull: github.events.append("disable"))
    # Act
    with pytest.raises(ValueError, match="re-enabled"):
        processor.process(github, 1, enabled=True)
    # Assert
    assert github.events == ["pending", "disable", "remember"]


def test_other_reviewer_changes_requested_blocks_clean_approval(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review(), _review(2, author="second", state="CHANGES_REQUESTED")]
    # Act
    processor.process(github, 1, enabled=True)
    # Assert
    assert "success" not in github.events


def test_clean_followup_does_not_override_earlier_nits(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename"), _review(2, author="second")]
    # Act
    processor.process(github, 1, enabled=True)
    # Assert
    assert "disable" in github.events


def test_retry_does_not_duplicate_notification(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename")]
    processor.process(github, 1, enabled=True)
    github.events.clear()
    # Act
    processor.process(github, 1, enabled=True)
    # Assert
    assert github.events == ["success"]


def test_delivery_failure_leaves_gate_successful_and_retries(
    github: FakeGitHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename")]

    def fail(*_: object) -> None:
        raise ValueError("No chat")

    monkeypatch.setattr(processor, "notify", fail)
    # Act
    result = processor.process(github, 1, enabled=True)
    # Assert
    assert (result, github.events, processor.memory_from(github.memory).notified) == (
        False,
        ["pending", "disable", "remember", "success"],
        set(),
    )


def test_manual_decision_survives_deleted_nit(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename")]
    processor.process(github, 1, enabled=True)
    github.reviews = [_review()]
    github.current = replace(github.current, auto=True)
    github.events.clear()
    # Act
    processor.process(github, 1, enabled=True)
    # Assert
    assert github.events == ["pending", "disable", "success"]


def test_dry_run_does_not_write_or_notify(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename")]
    # Act
    processor.process(github, 1, enabled=False)
    # Assert
    assert github.events == []


def test_draft_or_non_main_is_skipped(github: FakeGitHub) -> None:
    # Arrange
    github.current = replace(github.current, eligible=False)
    # Act
    processor.process(github, 1, enabled=True)
    # Assert
    assert github.events == []


@pytest.mark.parametrize("body", ["Nit: rename", "  nIt: rename", "Looks good\nNit: rename"])
def test_inline_nit_is_associated_with_approving_review(body: str) -> None:
    # Arrange
    review = processor.Review.parse(_review())
    comments = [{"pull_request_review_id": 1, "body": body}]
    # Act
    result = processor.nit_reviews([review], comments)
    # Assert
    assert result == [review]


def test_ordinary_mention_of_nits_is_not_a_nit() -> None:
    # Arrange
    review = processor.Review.parse(_review(body='Comments marked "Nit" are optional.'))
    # Act
    result = processor.nit_reviews([review], [])
    # Assert
    assert result == []


def test_human_comment_cannot_spoof_saved_state() -> None:
    # Arrange
    comments = [
        {
            "id": 10,
            "user": {"login": "author"},
            "body": processor.MARKER + '\n{"manual": true, "notified": [1]}',
        }
    ]
    # Act
    result = processor.memory_from(comments)
    # Assert
    assert result == processor.Memory()


@pytest.mark.parametrize(
    "response",
    [
        {"errors": [{"message": "Denied"}]},
        {},
        {
            "data": {
                "disablePullRequestAutoMerge": {
                    "pullRequest": {
                        "autoMergeRequest": {"enabledAt": "now"},
                    }
                }
            }
        },
    ],
)
def test_cancellation_requires_confirmed_api_response(
    response: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(processor.GitHub, "request", lambda *_args, **_kwargs: response)
    github = processor.GitHub("o/r", "token")
    # Act
    with pytest.raises(ValueError, match="cancellation"):
        github.disable(FakeGitHub().current)


def test_outsider_changes_requested_does_not_block_teammate_approval(github: FakeGitHub) -> None:
    # Arrange
    reviews = [processor.Review.parse(_review(state="CHANGES_REQUESTED"))]
    github.permission = "read"
    # Act
    result = processor.eligible_reviews(github, reviews)
    # Assert
    assert result == []


def test_status_reconciliation_does_not_post_identical_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    posts: list[object] = []
    statuses: list[object] = []

    def pages(_self: object, _path: str) -> list[object]:
        return statuses

    def repo(_self: object, _path: str, _method: str, **payload: object) -> None:
        posts.append(payload)
        statuses.insert(0, payload)

    monkeypatch.setattr(processor.GitHub, "pages", pages)
    monkeypatch.setattr(processor.GitHub, "repo", repo)
    github = processor.GitHub("o/r", "token")
    pull = FakeGitHub().current
    # Act
    github.status(pull, "success", "Done")
    github.status(pull, "success", "Done")
    # Assert
    assert len(posts) == 1


def test_pagination_reads_all_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    paths: list[str] = []

    def repo(_self: object, path: str) -> object:
        paths.append(path)
        return list(range(100)) if len(paths) == 1 else [100]

    monkeypatch.setattr(processor.GitHub, "repo", repo)
    github = processor.GitHub("o/r", "token")
    # Act
    result = github.pages("/pulls?state=open")
    # Assert
    assert (result, paths[-1]) == (list(range(101)), "/pulls?state=open&per_page=100&page=2")


def test_telegram_notification_escapes_names_and_links_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    requests: list[urllib.request.Request] = []

    def urlopen(request: urllib.request.Request, *, timeout: int) -> BytesIO:
        requests.append(request)
        assert timeout == 30
        return BytesIO(b'{"ok": true}')

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    pull = replace(FakeGitHub().current, author="<author>")
    # Act
    processor.notify(pull, processor.Review.parse(_review()))
    # Assert
    data = requests[0].data
    assert isinstance(data, bytes)
    assert b"&lt;author&gt;" in data


def test_missing_chat_id_does_not_send(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    # Act
    with pytest.raises(ValueError, match="chat ID"):
        processor.notify(FakeGitHub().current, processor.Review.parse(_review()))


def test_release_pr_does_not_emit_status_that_release_job_would_wait_for(
    github: FakeGitHub,
) -> None:
    # Arrange
    github.current = replace(github.current, release=True)
    # Act
    processor.process(github, 1, enabled=True)
    # Assert
    assert github.events == []


@pytest.mark.parametrize(
    ("author", "branch", "repository", "expected"),
    [
        ("whadio-release-bot[bot]", "chore/#275-release", "o/r", True),
        ("author", "chore/#275-release", "o/r", False),
        ("whadio-release-bot[bot]", "feature", "o/r", False),
        ("whadio-release-bot[bot]", "chore/#275-release", "fork/r", False),
    ],
)
def test_release_exemption_requires_app_and_protected_same_repo_branch(
    author: str,
    branch: str,
    repository: str,
    *,
    expected: bool,
) -> None:
    # Arrange
    item = {
        "number": 1,
        "head": {"sha": "head", "ref": branch, "repo": {"full_name": repository}},
        "base": {"ref": "main", "repo": {"full_name": "o/r"}},
        "user": {"login": author},
        "html_url": "https://github.com/o/r/pull/1",
        "node_id": "node",
        "state": "open",
        "draft": False,
        "auto_merge": None,
    }
    # Act
    result = processor.Pull.parse(item)
    # Assert
    assert result.release == expected
