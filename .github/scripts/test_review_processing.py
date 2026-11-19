import importlib.util
import json
import urllib.request
from dataclasses import replace
from email.message import Message
from http import HTTPStatus
from http.client import IncompleteRead
from io import BytesIO
from pathlib import Path
from types import ModuleType
from typing import Protocol
from urllib.error import HTTPError

import pytest


def _load() -> ModuleType:
    path = Path(__file__).with_name("review_processing.py")
    spec = importlib.util.spec_from_file_location("review_processing", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


processor = _load()
STATE_KEY = "test state key for the review queue"
REPOSITORY = "o/r"


def _review(
    identity: int = 1,
    *,
    state: str = "APPROVED",
    head: str | None = "head",
    author: str | None = "reviewer",
    body: str = "Looks good",
) -> object:
    return {
        "id": identity,
        "user": {"login": author} if author is not None else None,
        "state": state,
        "commit_id": head,
        "body": body,
        "html_url": "https://github.com/o/r/pull/1#review",
    }


class IMemory(Protocol):
    comment: int | None

    def body(self) -> str: ...


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
        self.memory_items: list[object] = []
        self.events: list[str] = []
        self.permission = "write"
        self.cancel_fails = False
        self.new_head = False
        self.reads = 0
        self.labeled = False

    def pull(self, _number: int) -> object:
        self.reads += 1
        if self.new_head and self.reads > 1:
            return replace(self.current, head="new-head")
        return self.current

    def open_numbers(self) -> set[int]:
        return {1} if self.current.eligible else set()

    def queued_pulls(self) -> set[int]:
        return {1} if self.labeled else set()

    def queue(self, _number: int) -> None:
        self.events.append("queue")
        self.labeled = True

    def unqueue(self, _number: int) -> None:
        self.events.append("unqueue")
        self.labeled = False

    def pages(self, path: str) -> list[object]:
        if path.endswith("/reviews"):
            return self.reviews
        if path == "/pulls/1/comments":
            return self.comments
        return self.memory_items

    def read_reviews(self, number: int) -> list[object]:
        reviews: list[object] = [
            processor.Review.parse(item) for item in self.pages(f"/pulls/{number}/reviews")
        ]
        return reviews

    def memory(self, _pull: object) -> object:
        return processor.memory_from(self.memory_items, STATE_KEY, REPOSITORY, 1)

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
        memory.comment = 10
        self.memory_items = [
            {
                "id": 10,
                "user": {"login": "github-actions[bot]"},
                "body": processor.seal_state(memory.body(), STATE_KEY, REPOSITORY, 1),
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
    processor.process(github, 1)
    # Assert
    assert github.events == ["success"]


@pytest.mark.parametrize("historical", [_review(head=None), _review(author=None)])
def test_nullable_history_does_not_block_current_approval(
    github: FakeGitHub, historical: object
) -> None:
    # Arrange
    github.reviews = [historical, _review(2)]
    # Act
    processor.process(github, 1)
    # Assert
    assert github.events == ["success"]


@pytest.mark.parametrize("unusable", [_review(head=None), _review(author=None)])
def test_nullable_approval_cannot_release_gate(github: FakeGitHub, unusable: object) -> None:
    # Arrange
    github.reviews = [unusable]
    # Act
    processor.process(github, 1)
    # Assert
    assert github.events == ["pending"]


def test_approval_submitted_during_inline_comment_read_cancels_auto_merge(
    github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    github.reviews = [_review()]
    pages = github.pages

    def read_pages(path: str) -> list[object]:
        if path == "/pulls/1/comments":
            github.reviews = [_review(), _review(2, author="teammate")]
            return [{"pull_request_review_id": 2, "body": "Nit: rename this"}]
        return pages(path)

    monkeypatch.setattr(github, "pages", read_pages)
    # Act
    processor.process(github, 1)
    # Assert
    assert github.events[:5] == ["pending", "disable", "queue", "remember", "success"]


def test_inline_nit_with_unavailable_review_keeps_gate_pending(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review()]
    github.comments = [{"pull_request_review_id": 2, "body": "Nit: rename this"}]
    # Act
    processor.process(github, 1)
    # Assert
    assert github.events == ["pending"]


def test_new_nits_before_status_publication_keep_gate_pending(
    github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    github.reviews = [_review()]
    memory = github.memory

    def memory_after_new_review(pull: object) -> object:
        github.reviews.append(_review(2, author="teammate", body="Nit: rename this"))
        return memory(pull)

    monkeypatch.setattr(github, "memory", memory_after_new_review)
    # Act
    processor.process(github, 1)
    # Assert
    assert github.events == ["pending"]


def test_waiting_for_first_approval_keeps_auto_merge_enabled(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = []
    # Act
    processor.process(github, 1)
    # Assert
    assert github.events == ["pending"]


def test_previous_clean_approval_keeps_auto_merge_enabled(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review(head="previous-head")]
    # Act
    processor.process(github, 1)
    # Assert
    assert github.events == ["pending"]


def test_review_processing_does_not_scan_other_prs(
    github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    github.reviews = [_review()]

    def fail() -> set[int]:
        pytest.fail("A targeted run should not list open pull requests")

    monkeypatch.setattr(github, "open_numbers", fail)
    # Act
    result = processor.reconcile(github, targets={1})
    # Assert
    assert result == 0


def test_nit_disables_before_releasing_gate_and_notifying(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename this")]
    # Act
    processor.process(github, 1)
    # Assert
    assert github.events == [
        "pending",
        "disable",
        "queue",
        "remember",
        "success",
        "notify",
        "remember",
        "unqueue",
    ]


def test_manual_merge_with_nits_is_allowed_after_processing(github: FakeGitHub) -> None:
    # Arrange
    github.current = replace(github.current, auto=False)
    github.reviews = [_review(body="Nit: rename this")]
    # Act
    processor.process(github, 1)
    # Assert
    assert github.events == [
        "pending",
        "queue",
        "remember",
        "success",
        "notify",
        "remember",
        "unqueue",
    ]


def test_failed_cancellation_never_releases_gate(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename this")]
    github.cancel_fails = True
    # Act
    with pytest.raises(ValueError, match="Cancellation failed"):
        processor.process(github, 1)
    # Assert
    assert github.events == ["pending", "disable"]


def test_new_head_during_processing_is_not_released(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review()]
    github.new_head = True
    # Act
    processor.process(github, 1)
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
    processor.process(github, 1)
    # Assert
    assert "success" not in github.events


def test_reader_approval_does_not_release_gate(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review()]
    github.permission = "read"
    # Act
    processor.process(github, 1)
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
    processor.process(github, 1)
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
        processor.process(github, 1)
    # Assert
    assert github.events == ["pending", "disable", "queue", "remember"]


def test_other_reviewer_changes_requested_blocks_clean_approval(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review(), _review(2, author="second", state="CHANGES_REQUESTED")]
    # Act
    processor.process(github, 1)
    # Assert
    assert "success" not in github.events


def test_clean_followup_does_not_override_earlier_nits(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename"), _review(2, author="second")]
    # Act
    processor.process(github, 1)
    # Assert
    assert "disable" in github.events


def test_clean_approval_on_new_head_allows_reenabled_auto_merge(github: FakeGitHub) -> None:
    # Arrange
    old_review = _review(body="Nit: rename")
    github.reviews = [old_review]
    processor.process(github, 1)
    github.current = replace(github.current, head="new-head", auto=True)
    github.reviews = [old_review, _review(2, head="new-head")]
    github.events.clear()
    # Act
    processor.process(github, 1)
    # Assert
    assert (github.current.auto, github.events) == (True, ["success"])


def test_retry_does_not_duplicate_notification(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename")]
    processor.process(github, 1)
    github.events.clear()
    # Act
    processor.process(github, 1)
    # Assert
    assert github.events == ["success"]


def test_delivery_failure_leaves_gate_successful_and_persists_notification(
    github: FakeGitHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename")]

    def fail(*_: object) -> None:
        raise ValueError("No chat")

    monkeypatch.setattr(processor, "notify", fail)
    # Act
    result = processor.process(github, 1)
    # Assert
    memory = processor.memory_from(github.memory_items, STATE_KEY, REPOSITORY, 1)
    assert (result, github.events, set(memory.pending)) == (
        False,
        ["pending", "disable", "queue", "remember", "success"],
        {1},
    )


def test_queue_write_failure_keeps_gate_pending(
    github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename")]

    def fail(*_: object) -> None:
        raise ValueError("Could not save review state")

    monkeypatch.setattr(github, "remember", fail)
    # Act
    result = processor.reconcile(github)
    # Assert
    assert (result, github.events) == (1, ["pending", "disable", "queue"])


def test_reconciliation_retries_saved_notification_after_merge(
    github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    github.reviews = [_review()]
    github.comments = [{"pull_request_review_id": 1, "body": "Nit: rename"}]

    def fail(*_: object) -> None:
        raise ValueError("Telegram is unreachable")

    with monkeypatch.context() as patch:
        patch.setattr(processor, "notify", fail)
        processor.reconcile(github)
    github.current = replace(github.current, eligible=False)
    github.reviews.clear()
    delivered: list[object] = []
    monkeypatch.setattr(processor, "notify", lambda _, notification: delivered.append(notification))
    # Act
    result = processor.reconcile(github)
    # Assert
    assert (result, delivered, github.labeled) == (
        0,
        [processor.Notification(1, "reviewer", "https://github.com/o/r/pull/1#review")],
        False,
    )


def test_truncated_telegram_response_does_not_abort_reconciliation(
    github: FakeGitHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename")]

    def truncate(*_: object) -> None:
        raise IncompleteRead(b'{"ok":')

    monkeypatch.setattr(processor, "notify", truncate)
    # Act
    result = processor.reconcile(github, targets={1, 2})
    # Assert
    assert (result, github.labeled, github.events.count("success")) == (2, True, 2)


def test_unauthenticated_queue_state_keeps_label(github: FakeGitHub) -> None:
    # Arrange
    github.current = replace(github.current, eligible=False)
    github.labeled = True
    # Act
    result = processor.reconcile(github)
    # Assert
    assert (result, github.labeled) == (1, True)


def test_inventory_does_not_parse_full_pull_request(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    def pages(_self: object, _path: str) -> list[object]:
        return [{"number": 1, "user": None}, {"number": 2}, {"user": None}]

    monkeypatch.setattr(processor.GitHub, "pages", pages)
    github = processor.GitHub(REPOSITORY, "test")
    # Act
    result = github.open_numbers()
    # Assert
    assert result == {1, 2}


@pytest.mark.parametrize(
    ("event", "payload", "expected"),
    [
        ("pull_request_target", {"pull_request": {"number": 2}}, {2}),
        ("workflow_run", {"workflow_run": {"pull_requests": [{"number": 3}]}}, {3}),
        ("workflow_run", {"workflow_run": {"pull_requests": []}}, set()),
        ("workflow_dispatch", {"inputs": {"pull_request": "7"}}, {7}),
        ("schedule", {}, None),
    ],
)
def test_event_targets_single_pr_when_known(
    event: str, payload: object, expected: set[int] | None
) -> None:
    # Arrange / Act
    result = processor.event_targets(event, payload)
    # Assert
    assert result == expected


def test_scheduled_inventory_includes_open_prs_and_closed_notification_retries(
    github: FakeGitHub, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(github, "queued_pulls", lambda: {1, 3})
    # Act
    processor.write_inventory(github, None)
    # Assert
    assert output.read_text(encoding="utf-8") == "pull_requests=[1, 3]\n"


def test_reconciliation_ignores_closed_prs_without_pending_labels(github: FakeGitHub) -> None:
    # Arrange
    github.current = replace(github.current, eligible=False)
    # Act
    processor.reconcile(github)
    # Assert
    assert github.reads == 0


def test_existing_memory_without_pending_notifications_preserves_delivery_history() -> None:
    # Arrange
    comments = [
        {
            "id": 10,
            "user": {"login": "github-actions[bot]"},
            "body": processor.seal_state(
                processor.MARKER + '\n{"manual": true, "notified": [1]}', STATE_KEY, REPOSITORY, 1
            ),
        }
    ]
    # Act
    memory = processor.memory_from(comments, STATE_KEY, REPOSITORY, 1)
    # Assert
    assert memory == processor.Memory(comment=10, notified={1})


def test_manual_decision_survives_deleted_nit(github: FakeGitHub) -> None:
    # Arrange
    github.reviews = [_review(body="Nit: rename")]
    processor.process(github, 1)
    github.reviews = [_review()]
    github.current = replace(github.current, auto=True)
    github.events.clear()
    # Act
    processor.process(github, 1)
    # Assert
    assert github.events == ["pending", "disable", "success"]


def test_main_processes_an_approval_with_nits_on_a_review_signal(
    github: FakeGitHub, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    path = tmp_path / "event.json"
    path.write_text('{"workflow_run": {"pull_requests": [{"number": 1}]}}', encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_run")
    monkeypatch.setenv("REVIEW_PROCESSING_STATE_KEY", STATE_KEY)
    monkeypatch.delenv("REVIEW_PROCESSING_TEST_PR", raising=False)
    monkeypatch.setattr(processor, "GitHub", lambda *_, **__: github)
    github.reviews = [_review(body="Nit: rename")]
    # Act
    processor.main()
    # Assert
    assert github.events == [
        "pending",
        "disable",
        "queue",
        "remember",
        "success",
        "notify",
        "remember",
        "unqueue",
    ]


def test_draft_or_non_main_is_skipped(github: FakeGitHub) -> None:
    # Arrange
    github.current = replace(github.current, eligible=False)
    # Act
    processor.process(github, 1)
    # Assert
    assert github.events == []


@pytest.mark.parametrize(("draft", "base"), [(True, "main"), (False, "other")])
def test_pull_parse_marks_draft_and_non_main_prs_ineligible(*, draft: bool, base: str) -> None:
    # Arrange
    payload = {
        "number": 1,
        "head": {"sha": "head"},
        "user": {"login": "author"},
        "html_url": "https://github.com/o/r/pull/1",
        "node_id": "PR_node",
        "state": "open",
        "base": {"ref": base},
        "draft": draft,
        "auto_merge": None,
    }
    # Act
    pull = processor.Pull.parse(payload)
    # Assert
    assert not pull.eligible


@pytest.mark.parametrize("body", ["Nit: rename", "  nIt: rename", "Looks good\nNit: rename"])
def test_inline_nit_is_associated_with_approving_review(body: str) -> None:
    # Arrange
    review = processor.Review.parse(_review())
    comments = [{"pull_request_review_id": 1, "body": body}]
    # Act
    result = processor.nit_reviews([review], processor.inline_nit_ids(comments))
    # Assert
    assert result == [review]


def test_ordinary_mention_of_nits_is_not_a_nit() -> None:
    # Arrange
    review = processor.Review.parse(_review(body='Comments marked "Nit" are optional.'))
    # Act
    result = processor.nit_reviews([review], set())
    # Assert
    assert result == []


def test_nit_in_changes_requested_review_is_ignored() -> None:
    # Arrange
    review = processor.Review.parse(_review(state="CHANGES_REQUESTED", body="Nit: rename"))
    # Act
    result = processor.nit_reviews([review], {1})
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
    result = processor.memory_from(comments, STATE_KEY, REPOSITORY, 1)
    # Assert
    assert result == processor.Memory()


@pytest.mark.parametrize("signed_number", [None, 2])
def test_other_actions_state_cannot_spoof_or_replay_saved_state(signed_number: int | None) -> None:
    # Arrange
    body = processor.MARKER + '\n{"manual": false, "notified": [1]}'
    if signed_number is not None:
        body = processor.seal_state(body, STATE_KEY, REPOSITORY, signed_number)
    comments = [{"id": 10, "user": {"login": "github-actions[bot]"}, "body": body}]
    # Act
    result = processor.memory_from(comments, STATE_KEY, REPOSITORY, 1)
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


def test_status_reconciliation_posts_success_again_after_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    success = {"context": processor.CONTEXT, "state": "success", "description": "Done"}
    statuses = [{"context": processor.CONTEXT, "state": "pending"}, success]
    posts: list[object] = []
    monkeypatch.setattr(processor.GitHub, "pages", lambda *_: statuses)
    monkeypatch.setattr(processor.GitHub, "repo", lambda *_, **payload: posts.append(payload))
    github = processor.GitHub(REPOSITORY, "token")
    # Act
    github.status(FakeGitHub().current, "success", "Done")
    # Assert
    assert posts == [success]


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


def test_notification_queue_searches_closed_pull_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    paths: list[str] = []

    def pages(_self: object, path: str) -> list[object]:
        paths.append(path)
        return [{"number": 12, "state": "closed", "pull_request": {}}, {"number": 13}]

    monkeypatch.setattr(processor.GitHub, "pages", pages)
    github = processor.GitHub("o/r", "token")
    # Act
    result = github.queued_pulls()
    # Assert
    assert (result, paths) == ({12}, ["/issues?state=all&labels=review-notification-pending"])


def test_queue_accepts_label_created_by_another_pr_run(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    label = f"/labels/{processor.PENDING_LABEL}"
    calls: list[tuple[str, str]] = []

    def repo(_self: object, path: str, method: str = "GET", **_: object) -> None:
        calls.append((path, method))
        if len(calls) == 1:
            raise HTTPError(path, HTTPStatus.NOT_FOUND, "", Message(), None)
        if path == "/labels":
            raise HTTPError(path, HTTPStatus.UNPROCESSABLE_ENTITY, "", Message(), None)

    monkeypatch.setattr(processor.GitHub, "repo", repo)
    github = processor.GitHub(REPOSITORY, "test")
    # Act
    github.queue(1)
    # Assert
    assert calls == [
        (label, "GET"),
        ("/labels", "POST"),
        (label, "GET"),
        ("/issues/1/labels", "POST"),
    ]


def test_telegram_notification_escapes_names_and_links_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    requests: list[urllib.request.Request] = []

    def urlopen(request: urllib.request.Request, *, timeout: int) -> BytesIO:
        requests.append(request)
        assert timeout == 5
        return BytesIO(b'{"ok": true}')

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    pull = replace(FakeGitHub().current, author="<author>")
    review_url = "https://github.com/o/r/pull/1#review"
    # Act
    processor.notify(pull, processor.Notification(1, "reviewer", review_url))
    # Assert
    data = requests[0].data
    assert isinstance(data, bytes)
    assert json.loads(data)["text"] == (
        '<a href="https://github.com/o/r/pull/1">PR #1</a> '
        "by &lt;author&gt; approved with nits by reviewer.\n"
        "Nits leave the reviewed commit for manual merging.\n"
        f'<a href="{review_url}">Review</a>'
    )


def test_missing_chat_id_does_not_send(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    # Act
    with pytest.raises(ValueError, match="chat ID"):
        processor.notify(
            FakeGitHub().current,
            processor.Notification(1, "reviewer", "https://github.com/o/r/pull/1#review"),
        )


def test_release_pr_does_not_emit_status_that_release_job_would_wait_for(
    github: FakeGitHub,
) -> None:
    # Arrange
    github.current = replace(github.current, release=True)
    # Act
    processor.process(github, 1)
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
