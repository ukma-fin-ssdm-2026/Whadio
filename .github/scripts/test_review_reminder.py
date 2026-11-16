import importlib.util
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


def test_no_ready_event_means_the_pull_request_was_never_a_draft() -> None:
    # Arrange
    events = [{"event": "labeled", "created_at": "2026-11-16T06:00:00Z"}]

    # Act
    result = reminder.last_ready(events)

    # Assert
    assert result is None
