import html
import importlib.util
import json
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

NOW = datetime(2026, 11, 16, 7, 0, tzinfo=UTC)


def _load() -> ModuleType:
    path = Path(__file__).with_name("review_reminder.py")
    spec = importlib.util.spec_from_file_location("review_reminder", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reminder = _load()


def _pull(
    number: int = 1,
    title: str = "feat(#1): add",
    author: str = "denys",
    *,
    draft: bool = False,
    hours: float = 3,
) -> object:
    return reminder.PullRequest(
        number,
        title,
        f"https://github.com/org/repo/pull/{number}",
        author,
        draft,
        NOW - timedelta(hours=hours),
    )


def test_pull_request_without_approval_waits() -> None:
    # Arrange
    pulls = [_pull(1)]

    # Act
    result = reminder.waiting(pulls, reviewed=set())

    # Assert
    assert [pull.number for pull in result] == [1]


def test_draft_pull_request_does_not_wait() -> None:
    # Arrange
    pulls = [_pull(1, draft=True)]

    # Act
    result = reminder.waiting(pulls, reviewed=set())

    # Assert
    assert result == []


def test_reviewed_pull_request_does_not_wait() -> None:
    # Arrange
    pulls = [_pull(1)]

    # Act
    result = reminder.waiting(pulls, reviewed={1})

    # Assert
    assert result == []


def test_longest_waiting_pull_request_comes_first() -> None:
    # Arrange
    pulls = [_pull(1, hours=2), _pull(2, hours=30)]

    # Act
    result = reminder.waiting(pulls, reviewed=set())

    # Assert
    assert [pull.number for pull in result] == [2, 1]


def test_approval_is_a_review() -> None:
    # Arrange
    reviews = [("ana", "COMMENTED"), ("bob", "APPROVED")]

    # Act
    result = reminder.is_reviewed(reviews)

    # Assert
    assert result is True


def test_change_request_is_a_review() -> None:
    # Arrange
    reviews = [("ana", "CHANGES_REQUESTED")]

    # Act
    result = reminder.is_reviewed(reviews)

    # Assert
    assert result is True


def test_comment_alone_is_no_review() -> None:
    # Arrange
    reviews = [("ana", "COMMENTED")]

    # Act
    result = reminder.is_reviewed(reviews)

    # Assert
    assert result is False


def test_dismissed_review_is_no_review() -> None:
    # Arrange
    reviews = [("ana", "APPROVED"), ("ana", "DISMISSED")]

    # Act
    result = reminder.is_reviewed(reviews)

    # Assert
    assert result is False


def test_comment_after_an_approval_keeps_it() -> None:
    # Arrange
    reviews = [("ana", "APPROVED"), ("ana", "COMMENTED")]

    # Act
    result = reminder.is_reviewed(reviews)

    # Assert
    assert result is True


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(minutes=20), "0 h"),
        (timedelta(hours=5, minutes=59), "5 h"),
        (timedelta(hours=24), "1 d 0 h"),
        (timedelta(days=2, hours=3), "2 d 3 h"),
        (timedelta(hours=-1), "0 h"),
    ],
)
def test_wait_is_written_in_hours_or_days_and_hours(delta: timedelta, expected: str) -> None:
    # Arrange / Act
    result = reminder.format_wait(delta)

    # Assert
    assert result == expected


def test_message_lists_number_link_title_author_and_wait() -> None:
    # Arrange
    pulls = [_pull(12, "fix(#9): retry", "ana", hours=50)]

    # Act
    message = reminder.build_message(pulls, NOW)

    # Assert
    assert message.splitlines()[1] == (
        '<a href="https://github.com/org/repo/pull/12">#12</a> fix(#9): retry by ana, '
        "waiting 2 d 2 h"
    )


def test_message_escapes_html_in_title_and_author() -> None:
    # Arrange
    pulls = [_pull(1, "fix: <b>&</b>", "a<i>")]

    # Act
    message = reminder.build_message(pulls, NOW)

    # Assert
    assert "fix: &lt;b&gt;&amp;&lt;/b&gt; by a&lt;i&gt;" in message


def test_message_header_counts_the_pull_requests() -> None:
    # Arrange
    pulls = [_pull(1), _pull(2)]

    # Act
    message = reminder.build_message(pulls, NOW)

    # Assert
    assert message.splitlines()[0] == "<b>2 pull request(s) waiting for review</b>"


def testlast_ready_event_restarts_the_wait() -> None:
    # Arrange
    events = [
        {"event": "labeled", "created_at": "2026-11-16T06:00:00Z"},
        {"event": "ready_for_review", "created_at": "2026-11-10T08:00:00Z"},
        {"event": "ready_for_review", "created_at": "2026-11-12T08:00:00Z"},
    ]

    # Act
    result = reminder.last_ready(events)

    # Assert
    assert result == datetime(2026, 11, 12, 8, 0, tzinfo=UTC)


def _shown(message: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", message))


def test_long_backlog_fits_telegrams_limit() -> None:
    # Arrange
    pulls = [_pull(number, "x" * 256, "some-author") for number in range(1, 16)]

    # Act
    message = reminder.build_message(pulls, NOW)

    # Assert
    assert len(_shown(message).encode("utf-16-le")) // 2 <= reminder.MESSAGE_LIMIT


def test_pull_requests_past_the_limit_are_counted_in_the_last_line() -> None:
    # Arrange
    pulls = [_pull(number, "x" * 256, "some-author") for number in range(1, 16)]

    # Act
    lines = reminder.build_message(pulls, NOW).splitlines()

    # Assert
    assert lines[-1] == f"and {15 - (len(lines) - 2)} more"


def test_short_backlog_lists_every_pull_request() -> None:
    # Arrange
    pulls = [_pull(number) for number in range(1, 16)]

    # Act
    lines = reminder.build_message(pulls, NOW).splitlines()

    # Assert
    assert len(lines) == 16


def _item(
    number: int, author: str = "denys", *, draft: bool = False, kind: str = "User"
) -> dict[str, object]:
    return {
        "number": number,
        "title": f"feat(#{number}): add",
        "html_url": f"https://github.com/org/repo/pull/{number}",
        "draft": draft,
        "created_at": "2026-11-16T04:00:00Z",
        "user": {"login": author, "type": kind},
    }


class FakeApis:
    def __init__(
        self, pulls: list[dict[str, object]], reviews: dict[int, list[dict[str, object]]]
    ) -> None:
        self.pulls = pulls
        self.reviews = reviews
        self.sent: list[dict[str, object]] = []

    def __call__(self, request: urllib.request.Request) -> object:
        url = urllib.parse.urlparse(request.full_url)
        if url.hostname == "api.telegram.org":
            assert isinstance(request.data, bytes)
            self.sent.append(json.loads(request.data))
            return {"ok": True}
        match url.path.removeprefix("/repos/org/repo").split("/"):
            case ["", "pulls"]:
                return self.pulls
            case ["", "issues", _, "events"]:
                return []
            case ["", "pulls", number, "reviews"]:
                return self.reviews.get(int(number), [])
            case _:
                pytest.fail(f"Unexpected request to {request.full_url}")


def _run(monkeypatch: pytest.MonkeyPatch, apis: FakeApis) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(reminder, "_request", apis)
    reminder.main()


def test_reminder_lists_only_pull_requests_waiting_for_a_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    apis = FakeApis(
        pulls=[
            _item(1),
            _item(2, draft=True),
            _item(3, "dependabot[bot]", kind="Bot"),
            _item(4),
            _item(5),
        ],
        reviews={
            4: [{"state": "APPROVED", "user": {"login": "ana"}}],
            5: [{"state": "COMMENTED", "user": {"login": "ana"}}],
        },
    )

    # Act
    _run(monkeypatch, apis)

    # Assert
    assert [
        (message["chat_id"], re.findall(r">#(\d+)<", str(message["text"]))) for message in apis.sent
    ] == [("42", ["1", "5"])]


def test_reminder_sends_nothing_when_no_pull_request_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    apis = FakeApis(
        pulls=[_item(1, draft=True), _item(2)],
        reviews={2: [{"state": "CHANGES_REQUESTED", "user": {"login": "ana"}}]},
    )

    # Act
    _run(monkeypatch, apis)

    # Assert
    assert apis.sent == []


def test_no_ready_event_means_the_pull_request_was_never_a_draft() -> None:
    # Arrange
    events = [{"event": "labeled", "created_at": "2026-11-16T06:00:00Z"}]

    # Act
    result = reminder.last_ready(events)

    # Assert
    assert result is None
