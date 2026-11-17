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
    title: str | None = None,
    *,
    hours: float = 3,
    pushed: float = 3,
    verdicts: dict[str, tuple[str, float]] | None = None,
) -> object:
    return reminder.PullRequest(
        number,
        title or f"feat(#{number}): add",
        f"https://github.com/org/repo/pull/{number}",
        "denys",
        NOW - timedelta(hours=hours),
        NOW - timedelta(hours=pushed),
        {
            reviewer: (state, NOW - timedelta(hours=ago))
            for reviewer, (state, ago) in (verdicts or {}).items()
        },
    )


def test_pull_request_without_a_verdict_is_not_reviewed_yet() -> None:
    # Arrange
    pull = _pull(1, hours=5)

    # Act
    entry = reminder.classify(pull)

    # Assert
    assert (entry.section, entry.names, entry.since) == (
        "Not reviewed yet",
        "denys",
        NOW - timedelta(hours=5),
    )


def test_pull_request_with_only_approvals_is_not_listed() -> None:
    # Arrange
    pull = _pull(verdicts={"ana": ("APPROVED", 10), "bob": ("APPROVED", 9)})

    # Act
    entry = reminder.classify(pull)

    # Assert
    assert entry is None


def test_approval_stands_through_a_later_push() -> None:
    # Arrange
    pull = _pull(pushed=1, verdicts={"ana": ("APPROVED", 10)})

    # Act
    entry = reminder.classify(pull)

    # Assert
    assert entry is None


def test_change_request_after_the_last_push_waits_for_fixes() -> None:
    # Arrange
    pull = _pull(pushed=10, verdicts={"ana": ("CHANGES_REQUESTED", 4)})

    # Act
    entry = reminder.classify(pull)

    # Assert
    assert (entry.section, entry.names, entry.since) == (
        "Waiting for fixes",
        "denys",
        NOW - timedelta(hours=4),
    )


def test_change_request_before_the_last_push_waits_for_a_re_review() -> None:
    # Arrange
    pull = _pull(pushed=4, verdicts={"ana": ("CHANGES_REQUESTED", 10)})

    # Act
    entry = reminder.classify(pull)

    # Assert
    assert (entry.section, entry.names, entry.since) == (
        "Waiting for a re-review",
        "ana",
        NOW - timedelta(hours=4),
    )


def test_re_review_names_every_reviewer_with_a_standing_change_request() -> None:
    # Arrange
    pull = _pull(
        pushed=2,
        verdicts={
            "bob": ("CHANGES_REQUESTED", 8),
            "cat": ("APPROVED", 9),
            "ana": ("CHANGES_REQUESTED", 10),
        },
    )

    # Act
    entry = reminder.classify(pull)

    # Assert
    assert entry.names == "ana, bob"


def test_approval_after_the_push_does_not_hide_an_older_change_request() -> None:
    # Arrange
    pull = _pull(
        pushed=6,
        verdicts={"ana": ("CHANGES_REQUESTED", 10), "bob": ("APPROVED", 2)},
    )

    # Act
    entry = reminder.classify(pull)

    # Assert
    assert (entry.section, entry.names) == ("Waiting for a re-review", "ana")


def test_change_request_after_the_push_beats_an_earlier_approval() -> None:
    # Arrange
    pull = _pull(
        pushed=10,
        verdicts={"ana": ("APPROVED", 9), "bob": ("CHANGES_REQUESTED", 3)},
    )

    # Act
    entry = reminder.classify(pull)

    # Assert
    assert entry.section == "Waiting for fixes"


def test_one_fresh_change_request_among_older_ones_waits_for_fixes_from_the_newest() -> None:
    # Arrange
    pull = _pull(
        pushed=6,
        verdicts={"ana": ("CHANGES_REQUESTED", 10), "bob": ("CHANGES_REQUESTED", 2)},
    )

    # Act
    entry = reminder.classify(pull)

    # Assert
    assert (entry.section, entry.since) == ("Waiting for fixes", NOW - timedelta(hours=2))


def _review(reviewer: str, state: str, hours_ago: float) -> dict[str, object]:
    return {
        "state": state,
        "user": {"login": reviewer},
        "submitted_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
    }


def test_latest_verdict_of_a_reviewer_stands() -> None:
    # Arrange
    reviews = [_review("ana", "CHANGES_REQUESTED", 9), _review("ana", "APPROVED", 3)]

    # Act
    result = reminder.standing_verdicts(reviews)

    # Assert
    assert result == {"ana": ("APPROVED", NOW - timedelta(hours=3))}


def test_comments_are_ignored() -> None:
    # Arrange
    reviews = [_review("ana", "COMMENTED", 9), _review("bob", "APPROVED", 8)]

    # Act
    result = reminder.standing_verdicts(reviews)

    # Assert
    assert list(result) == ["bob"]


def test_comment_after_a_verdict_keeps_it() -> None:
    # Arrange
    reviews = [_review("ana", "CHANGES_REQUESTED", 9), _review("ana", "COMMENTED", 3)]

    # Act
    result = reminder.standing_verdicts(reviews)

    # Assert
    assert result == {"ana": ("CHANGES_REQUESTED", NOW - timedelta(hours=9))}


def test_dismissal_withdraws_the_verdict() -> None:
    # Arrange
    reviews = [_review("ana", "APPROVED", 9), _review("ana", "DISMISSED", 3)]

    # Act
    result = reminder.standing_verdicts(reviews)

    # Assert
    assert result == {}


def test_verdict_after_a_dismissal_stands() -> None:
    # Arrange
    reviews = [
        _review("ana", "CHANGES_REQUESTED", 9),
        _review("ana", "DISMISSED", 8),
        _review("ana", "APPROVED", 2),
    ]

    # Act
    result = reminder.standing_verdicts(reviews)

    # Assert
    assert result == {"ana": ("APPROVED", NOW - timedelta(hours=2))}


def test_pending_review_is_ignored() -> None:
    # Arrange
    reviews = [{"state": "PENDING", "user": {"login": "ana"}}]

    # Act
    result = reminder.standing_verdicts(reviews)

    # Assert
    assert result == {}


def test_sections_come_in_order_and_each_lists_the_longest_wait_first() -> None:
    # Arrange
    pulls = [
        _pull(1, pushed=1, verdicts={"ana": ("CHANGES_REQUESTED", 0.5)}),
        _pull(2, hours=2),
        _pull(3, pushed=5, verdicts={"ana": ("CHANGES_REQUESTED", 20)}),
        _pull(4, hours=30),
        _pull(5, pushed=8, verdicts={"ana": ("CHANGES_REQUESTED", 7)}),
        _pull(6, pushed=3, verdicts={"ana": ("CHANGES_REQUESTED", 20)}),
        _pull(7, verdicts={"ana": ("APPROVED", 4)}),
    ]

    # Act
    result = reminder.waiting(pulls)

    # Assert
    assert [(entry.section, entry.pull.number) for entry in result] == [
        ("Not reviewed yet", 4),
        ("Not reviewed yet", 2),
        ("Waiting for a re-review", 3),
        ("Waiting for a re-review", 6),
        ("Waiting for fixes", 5),
        ("Waiting for fixes", 1),
    ]


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


def test_message_lists_number_link_title_person_and_wait() -> None:
    # Arrange
    entries = reminder.waiting([_pull(12, "fix(#9): retry", hours=50)])

    # Act
    message = reminder.build_message(entries, NOW)

    # Assert
    assert message.splitlines()[1] == (
        '<a href="https://github.com/org/repo/pull/12">#12</a> fix(#9): retry by denys, '
        "waiting 2 d 2 h"
    )


def test_message_escapes_html_in_title_and_person() -> None:
    # Arrange
    pull = _pull(1, "fix: <b>&</b>", pushed=1, verdicts={"a<i>": ("CHANGES_REQUESTED", 5)})
    entries = reminder.waiting([pull])

    # Act
    message = reminder.build_message(entries, NOW)

    # Assert
    assert "fix: &lt;b&gt;&amp;&lt;/b&gt; by denys, re-review from a&lt;i&gt;" in message


def test_message_headers_are_bold_and_count_their_pull_requests() -> None:
    # Arrange
    entries = reminder.waiting(
        [
            _pull(1),
            _pull(2),
            _pull(3, pushed=1, verdicts={"ana": ("CHANGES_REQUESTED", 5)}),
            _pull(4, pushed=5, verdicts={"ana": ("CHANGES_REQUESTED", 1)}),
        ]
    )

    # Act
    message = reminder.build_message(entries, NOW)

    # Assert
    assert re.findall(r"<b>(.*?)</b>", message) == [
        "Not reviewed yet (2)",
        "Waiting for a re-review (1)",
        "Waiting for fixes (1)",
    ]


def test_empty_sections_are_left_out() -> None:
    # Arrange
    entries = reminder.waiting([_pull(1, pushed=1, verdicts={"ana": ("CHANGES_REQUESTED", 5)})])

    # Act
    message = reminder.build_message(entries, NOW)

    # Assert
    assert message.splitlines() == [
        "<b>Waiting for a re-review (1)</b>",
        (
            '<a href="https://github.com/org/repo/pull/1">#1</a> feat(#1): add by denys, '
            "re-review from ana, waiting 1 h"
        ),
    ]


def test_sections_are_separated_by_a_blank_line() -> None:
    # Arrange
    entries = reminder.waiting(
        [_pull(1), _pull(2, pushed=1, verdicts={"ana": ("CHANGES_REQUESTED", 5)})]
    )

    # Act
    lines = reminder.build_message(entries, NOW).splitlines()

    # Assert
    assert lines[2] == ""


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


def _backlog() -> object:
    return reminder.waiting(
        [_pull(number, "x" * 256, hours=number) for number in range(1, 9)]
        + [
            _pull(number, "x" * 256, pushed=1, verdicts={"ana": ("CHANGES_REQUESTED", number)})
            for number in range(9, 16)
        ]
    )


def test_long_backlog_fits_telegrams_limit() -> None:
    # Arrange
    entries = _backlog()

    # Act
    message = reminder.build_message(entries, NOW)

    # Assert
    assert len(_shown(message).encode("utf-16-le")) // 2 <= reminder.MESSAGE_LIMIT


def test_pull_requests_past_the_limit_are_counted_in_the_last_line() -> None:
    # Arrange
    entries = _backlog()

    # Act
    lines = reminder.build_message(entries, NOW).splitlines()

    # Assert
    listed = len(re.findall(r"^<a ", "\n".join(lines), flags=re.MULTILINE))
    assert lines[-1] == f"and {15 - listed} more"


def test_short_backlog_lists_every_pull_request() -> None:
    # Arrange
    entries = reminder.waiting([_pull(number) for number in range(1, 16)])

    # Act
    lines = reminder.build_message(entries, NOW).splitlines()

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
        "head": {"sha": f"sha{number}"},
        "user": {"login": author, "type": kind},
    }


class FakeApis:
    def __init__(
        self,
        pulls: list[dict[str, object]],
        reviews: dict[int, list[dict[str, object]]],
        pushes: dict[int, str] | None = None,
    ) -> None:
        self.pulls = pulls
        self.reviews = reviews
        self.pushes = pushes or {}
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
            case ["", "commits", sha]:
                date = self.pushes.get(int(sha.removeprefix("sha")), "2026-11-16T04:00:00Z")
                return {"commit": {"committer": {"date": date}}}
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


def _verdict(reviewer: str, state: str, submitted_at: str) -> dict[str, object]:
    return {"state": state, "user": {"login": reviewer}, "submitted_at": submitted_at}


def test_reminder_sorts_pull_requests_into_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    apis = FakeApis(
        pulls=[
            _item(1),
            _item(2, draft=True),
            _item(3, "dependabot[bot]", kind="Bot"),
            _item(4),
            _item(5),
            _item(6),
            _item(7),
        ],
        reviews={
            4: [_verdict("ana", "APPROVED", "2026-11-16T05:00:00Z")],
            5: [_verdict("ana", "COMMENTED", "2026-11-16T05:00:00Z")],
            6: [_verdict("ana", "CHANGES_REQUESTED", "2026-11-16T05:00:00Z")],
            7: [_verdict("ana", "CHANGES_REQUESTED", "2026-11-16T05:00:00Z")],
        },
        pushes={6: "2026-11-16T06:00:00Z"},
    )

    # Act
    _run(monkeypatch, apis)

    # Assert
    assert [
        (message["chat_id"], re.findall(r"<b>(.*?) \(|>#(\d+)<", str(message["text"])))
        for message in apis.sent
    ] == [
        (
            "42",
            [
                ("Not reviewed yet", ""),
                ("", "1"),
                ("", "5"),
                ("Waiting for a re-review", ""),
                ("", "6"),
                ("Waiting for fixes", ""),
                ("", "7"),
            ],
        )
    ]


def test_reminder_sends_nothing_when_nothing_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    apis = FakeApis(
        pulls=[_item(1, draft=True), _item(2)],
        reviews={2: [_verdict("ana", "APPROVED", "2026-11-16T05:00:00Z")]},
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
