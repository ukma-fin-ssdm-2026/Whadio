import importlib.util
import urllib.parse
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import BaseModel


def _load() -> ModuleType:
    path = Path(__file__).with_name("dora_metrics.py")
    spec = importlib.util.spec_from_file_location("dora_metrics", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dora = _load()

START = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
PERIOD = dora.Period(date(2026, 10, 20), date(2026, 11, 10))
ORDER = {"a": 0, "b": 1, "c": 2, "d": 3}
AFTER_PERIOD = 16 * 24 * 60


def _at(minutes: float) -> datetime:
    return START + timedelta(minutes=minutes)


def _run(
    run_id: int,
    conclusion: str = "success",
    *,
    created: float = 0,
    updated: float = 0,
    sha: str = "",
) -> object:
    return dora.Run(
        database_id=run_id,
        head_sha=sha or f"sha{run_id}",
        workflow_name="CI/CD",
        event="push",
        conclusion=conclusion,
        attempt=1,
        created_at=_at(created),
        updated_at=_at(updated),
    )


def _job(started: float, ended: float, runner: str | None = "ssdm-1") -> object:
    return dora.Job(
        name="Checks",
        conclusion="skipped" if runner is None else "success",
        started_at=_at(started),
        completed_at=_at(ended),
        runner_name=runner,
    )


def _pull(
    number: int, *, author: str = "Hukyl", first: float = 0, merged: float = 0, sha: str = ""
) -> object:
    return dora.PullRequest(
        number=number,
        author=author,
        first_commit_at=_at(first),
        merged_at=_at(merged),
        merge_commit=sha or f"merge{number}",
        deployed_by=1,
    )


@pytest.mark.parametrize(
    "moment",
    [
        pytest.param(datetime(2026, 10, 19, 21, 0, tzinfo=UTC), id="first-midnight-summer-time"),
        pytest.param(datetime(2026, 11, 9, 21, 59, 59, tzinfo=UTC), id="last-second-winter-time"),
    ],
)
def test_moment_between_the_kyiv_midnights_is_in_the_period(moment: datetime) -> None:
    # Arrange / Act
    inside = moment in PERIOD

    # Assert
    assert inside


@pytest.mark.parametrize(
    "moment",
    [
        pytest.param(datetime(2026, 10, 19, 20, 59, 59, tzinfo=UTC), id="before-first-midnight"),
        pytest.param(datetime(2026, 11, 9, 22, 0, tzinfo=UTC), id="closing-midnight"),
    ],
)
def test_moment_outside_the_kyiv_midnights_is_not_in_the_period(moment: datetime) -> None:
    # Arrange / Act
    inside = moment in PERIOD

    # Assert
    assert not inside


def test_period_counts_calendar_weeks_across_the_clock_change() -> None:
    # Arrange / Act
    weeks = PERIOD.weeks

    # Assert
    assert weeks == 3


@pytest.mark.parametrize(
    ("jobs", "expected"),
    [
        pytest.param(
            [_job(2, 3, runner=None), _job(5, 9)],
            dora.Timing(_at(0), _at(5), _at(9)),
            id="queue-until-first-job-with-runner",
        ),
        pytest.param(
            [_job(1, 4), _job(5, 9), _job(9, 12, runner=None)],
            dora.Timing(_at(0), _at(1), _at(9)),
            id="run-until-last-job-with-runner",
        ),
        pytest.param([_job(0, 1, runner=""), _job(1, 1, runner=None)], None, id="never-got-runner"),
    ],
)
def test_timing_counts_only_the_jobs_that_got_a_runner(
    jobs: list[object], expected: object
) -> None:
    # Arrange
    run = _run(1)

    # Act
    timing = dora.timing(run, jobs)

    # Assert
    assert timing == expected


def test_each_red_run_in_a_row_recovers_when_the_next_green_run_ends() -> None:
    # Arrange
    runs = [
        _run(1, "failure", created=0),
        _run(2, "failure", created=10),
        _run(3, "cancelled", created=20),
        _run(4, created=30),
    ]
    finished = {1: _at(5), 2: _at(15), 3: _at(20), 4: _at(40)}

    # Act
    times = dora.recovery_times(runs, finished)

    # Assert
    assert times == [timedelta(minutes=35), timedelta(minutes=25)]


def test_red_run_with_no_later_green_run_has_no_recovery() -> None:
    # Arrange
    runs = [_run(1, created=0), _run(2, "failure", created=10)]

    # Act
    times = dora.recovery_times(runs, {1: _at(5), 2: _at(15)})

    # Assert
    assert times == []


def test_red_run_at_the_end_of_the_period_recovers_at_the_next_green_run_after_it() -> None:
    # Arrange
    runs = [_run(1, "failure", updated=5), _run(2, created=AFTER_PERIOD, updated=AFTER_PERIOD)]
    recovery = timedelta(minutes=AFTER_PERIOD - 5)

    # Act
    summary = dora.summarise(PERIOD, runs, {}, [])

    # Assert
    assert summary.recovery == dora.Spread(1, recovery, recovery)


def test_green_run_after_the_period_is_not_a_deployment() -> None:
    # Arrange
    runs = [_run(1, "failure"), _run(2, created=AFTER_PERIOD)]

    # Act
    summary = dora.summarise(PERIOD, runs, {}, [])

    # Assert
    assert summary.green == 0


def test_red_run_after_the_period_has_no_recovery_of_its_own() -> None:
    # Arrange
    runs = [
        _run(1, "failure"),
        _run(2, "failure", created=AFTER_PERIOD),
        _run(3, created=AFTER_PERIOD + 10),
    ]

    # Act
    summary = dora.summarise(PERIOD, runs, {}, [])

    # Assert
    assert summary.recovery.count == 1


def test_pull_request_deployed_after_the_period_has_no_lead_time() -> None:
    # Arrange
    runs = [_run(2, "failure"), _run(1, created=AFTER_PERIOD)]
    jobs = {1: [_job(AFTER_PERIOD, AFTER_PERIOD + 10)]}

    # Act
    summary = dora.summarise(PERIOD, runs, jobs, [_pull(1)])

    # Assert
    assert summary.lead is None


def test_red_run_with_no_later_green_run_is_not_yet_recovered() -> None:
    # Arrange
    runs = [_run(1), _run(2, "failure", created=10)]

    # Act
    summary = dora.summarise(PERIOD, runs, {}, [])

    # Assert
    assert summary.unrecovered == 1


def test_red_run_without_a_runner_recovers_from_its_last_update() -> None:
    # Arrange
    runs = [_run(1, "failure", updated=2), _run(2, created=10)]
    jobs = {1: [_job(0, 1, runner="")], 2: [_job(10, 30)]}

    # Act
    summary = dora.summarise(PERIOD, runs, jobs, [])

    # Assert
    assert summary.recovery.median == timedelta(minutes=28)


def test_cancelled_runs_do_not_count_towards_the_change_fail_rate() -> None:
    # Arrange
    runs = [_run(1), _run(2, "failure"), _run(3, "cancelled"), _run(4, "cancelled")]

    # Act
    summary = dora.summarise(PERIOD, runs, {}, [])

    # Assert
    assert summary.change_fail_rate == 0.5


def test_runs_created_outside_the_period_are_left_out() -> None:
    # Arrange
    runs = [_run(1), _run(2, created=-8 * 24 * 60)]

    # Act
    summary = dora.summarise(PERIOD, runs, {}, [])

    # Assert
    assert summary.runs == 1


def test_release_bot_pull_requests_are_left_out_of_the_team_lead_time() -> None:
    # Arrange
    pulls = [_pull(1, first=0), _pull(2, author=dora.RELEASE_BOT, first=50)]

    # Act
    summary = dora.summarise(PERIOD, [_run(1, created=60)], {1: [_job(60, 70)]}, pulls)

    # Assert
    assert summary.team_lead.median == timedelta(minutes=70)


def test_green_run_of_a_release_bot_commit_is_left_out_of_the_team_frequency() -> None:
    # Arrange
    runs = [_run(1, sha="release"), _run(2, sha="feature")]
    pulls = [_pull(1, author=dora.RELEASE_BOT, sha="release")]

    # Act
    summary = dora.summarise(PERIOD, runs, {}, pulls)

    # Assert
    assert summary.team_green == 1


def test_lead_time_splits_into_review_waiting_queue_and_run() -> None:
    # Arrange
    deployed = dora.Timing(_at(90), _at(95), _at(105))

    # Act
    lead = dora.lead_time(_pull(1, merged=60), deployed)

    # Assert
    assert (lead.before_merge, lead.waiting, lead.queue, lead.run) == tuple(
        timedelta(minutes=minutes) for minutes in (60, 30, 5, 10)
    )


def test_wait_for_a_green_main_is_never_negative() -> None:
    # Arrange
    deployed = dora.Timing(_at(9), _at(12), _at(20))

    # Act
    lead = dora.lead_time(_pull(1, merged=10), deployed)

    # Assert
    assert lead.waiting == timedelta()


def test_queue_share_weighs_each_pull_request_by_its_deploying_run() -> None:
    # Arrange
    leads = [
        dora.lead_time(_pull(1), dora.Timing(_at(0), _at(30), _at(40))),
        dora.lead_time(_pull(2), dora.Timing(_at(0), _at(0), _at(10))),
    ]

    # Act
    share = dora.queue_share(leads)

    # Assert
    assert share == 0.6


@pytest.mark.parametrize(
    ("merge_commit", "runs", "expected"),
    [
        pytest.param("b", [_run(1, sha="b"), _run(2, sha="d")], [(7, 1)], id="own-green-run"),
        pytest.param(
            "b",
            [_run(1, "cancelled", sha="b"), _run(2, "failure", sha="c"), _run(3, sha="d")],
            [(7, 3)],
            id="own-run-cancelled-next-red",
        ),
        pytest.param(
            "b",
            [_run(1, sha="d", created=10), _run(2, sha="c", created=50)],
            [(7, 2)],
            id="closest-on-main-though-created-later",
        ),
        pytest.param("c", [_run(1, sha="b")], [], id="green-run-only-before-merge"),
        pytest.param("x", [_run(1, sha="b")], [], id="merge-off-first-parent-history"),
    ],
)
def test_pull_request_is_deployed_by_the_first_green_run_at_or_after_its_merge_on_main(
    merge_commit: str, runs: list[object], expected: list[tuple[int, int]]
) -> None:
    # Arrange
    merge = dora.Merge(7, "Hukyl", START, merge_commit)

    # Act
    deployed = dora.deployments([merge], runs, ORDER)

    # Assert
    assert [(m.number, run.database_id) for m, run in deployed] == expected


def test_first_parent_order_leaves_out_commits_of_merged_branches() -> None:
    # Arrange
    first_parents = {"c": "b", "b": "a", "x": "a"}

    # Act
    order = dora.first_parent_order("c", first_parents)

    # Assert
    assert order == {"a": 0, "b": 1, "c": 2}


def test_bot_author_is_named_as_gh_names_it() -> None:
    # Arrange
    user = dora.GitHubUser(login="whadio-release-bot[bot]", type="Bot")

    # Act
    name = user.shown()

    # Assert
    assert name == "app/whadio-release-bot"


def test_run_reads_the_rest_payload_of_the_actions_api() -> None:
    # Arrange
    payload = {
        "id": 5,
        "head_sha": "a",
        "name": "CI/CD",
        "event": "push",
        "conclusion": "success",
        "run_attempt": 2,
        "created_at": "2026-10-25T09:00:00Z",
        "updated_at": "2026-10-25T09:10:00Z",
    }

    # Act
    run = dora.Run.model_validate(payload)

    # Assert
    assert (run.database_id, run.workflow_name, run.attempt) == (5, "CI/CD", 2)


def test_evidence_file_holds_one_compact_object_per_line(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "runs.json"

    # Act
    dora.write_evidence(path, [_run(1)])

    # Assert
    assert path.read_text() == (
        '[\n{"databaseId":1,"headSha":"sha1","workflowName":"CI/CD","event":"push",'
        '"conclusion":"success","attempt":1,"createdAt":"2026-10-25T09:00:00Z",'
        '"updatedAt":"2026-10-25T09:00:00Z"}\n]\n'
    )


def test_report_shows_the_change_fail_rate_of_completed_runs() -> None:
    # Arrange
    summary = dora.summarise(PERIOD, [_run(1), _run(2, "failure"), _run(3, "cancelled")], {}, [])

    # Act
    report = dora.render(summary)

    # Assert
    assert "| Change fail rate | 1 / 2 = **50.0%** |" in report.splitlines()


def test_report_counts_the_red_runs_not_yet_recovered() -> None:
    # Arrange
    summary = dora.summarise(PERIOD, [_run(1), _run(2, "failure", created=10)], {}, [])

    # Act
    report = dora.render(summary)

    # Assert
    assert (
        f"| Failed deployment recovery time | {dora.DASH}; not yet recovered: 1 |"
        in report.splitlines()
    )


def test_export_adds_the_green_run_after_the_period_that_recovers_its_last_red_run() -> None:
    # Arrange
    runs = [
        _run(1),
        _run(2, "failure", created=10),
        _run(3, "cancelled", created=20),
        _run(4, "failure", created=AFTER_PERIOD),
        _run(5, created=AFTER_PERIOD + 10),
        _run(6, created=AFTER_PERIOD + 20),
    ]

    # Act
    exported = dora.exported_runs(runs, PERIOD)

    # Assert
    assert [run.database_id for run in exported] == [1, 2, 3, 5]


def test_export_holds_only_the_period_when_its_last_completed_run_is_green() -> None:
    # Arrange
    runs = [_run(1, "failure"), _run(2, created=10), _run(3, created=AFTER_PERIOD)]

    # Act
    exported = dora.exported_runs(runs, PERIOD)

    # Assert
    assert [run.database_id for run in exported] == [1, 2]


def _json(model: object) -> str:
    assert isinstance(model, BaseModel)
    return model.model_dump_json()


def _within(window: str, moment: datetime) -> bool:
    since, until = (datetime.fromisoformat(end) for end in window.split(".."))
    return since <= moment <= until


class FakeRunsApi:
    def __init__(self, runs_per_day: Mapping[date, int]) -> None:
        offsets = [
            (day - START.date()).days * 24 * 60
            for day, count in runs_per_day.items()
            for _ in range(count)
        ]
        self.runs = sorted(
            ((_at(offset), _run(run_id, created=offset)) for run_id, offset in enumerate(offsets)),
            key=lambda pair: pair[0],
            reverse=True,
        )

    def __call__(self, path: str) -> bytes:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
        windows = query.get("created", [])
        matching = [
            run for moment, run in self.runs if all(_within(window, moment) for window in windows)
        ]
        size = int(query["per_page"][0])
        start = (int(query.get("page", ["1"])[0]) - 1) * size
        listed = matching[: dora.RUN_LIMIT][start : start + size]
        rows = ",".join(_json(run) for run in listed)
        return f'{{"total_count":{len(matching)},"workflow_runs":[{rows}]}}'.encode()


def test_runs_of_a_range_over_the_limit_are_all_fetched_by_splitting_it() -> None:
    # Arrange
    api = FakeRunsApi({date(2026, 10, 26): 600, date(2026, 10, 27): 600})

    # Act
    runs = dora.runs_created(date(2026, 10, 26), date(2026, 10, 27), api)

    # Assert
    assert len({run.database_id for run in runs}) == 1200


def test_newer_runs_over_the_limit_do_not_hide_the_runs_of_the_range() -> None:
    # Arrange
    api = FakeRunsApi({date(2026, 11, 5): 130, date(2026, 11, 12): 1000})

    # Act
    runs = dora.runs_created(PERIOD.since, date(2026, 11, 9), api)

    # Assert
    assert len(runs) == 130


def test_day_with_more_runs_than_github_lists_fails_the_fetch() -> None:
    # Arrange
    api = FakeRunsApi({date(2026, 10, 26): 1000})

    # Act / Assert
    with pytest.raises(dora.RunLimitError, match=r"26\.10\.2026"):
        dora.runs_created(date(2026, 10, 26), date(2026, 10, 26), api)
