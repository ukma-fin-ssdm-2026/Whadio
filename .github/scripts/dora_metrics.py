import argparse
import os
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from bisect import bisect_left
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from pydantic.alias_generators import to_camel

GITHUB_API = "https://api.github.com/repos/ukma-fin-ssdm-2026/Whadio"
RUNS = "actions/workflows/ci.yml/runs?branch=main&event=push"
PAGE_SIZE = 100
# GitHub lists at most this many runs for a query filtered by branch, event or date
RUN_LIMIT = 1000
TIMEOUT_SECONDS = 30
KYIV = ZoneInfo("Europe/Kyiv")
DASH = "\N{EN DASH}"
RELEASE_BOT = "app/whadio-release-bot"
CI_CD = Path(__file__).resolve().parents[2] / "docs" / "ci-cd"
EVIDENCE = CI_CD / "evidence"

Conclusion = Literal[
    "action_required",
    "cancelled",
    "failure",
    "neutral",
    "skipped",
    "stale",
    "startup_failure",
    "success",
    "timed_out",
]
_CAMEL = ConfigDict(
    alias_generator=to_camel, validate_by_name=True, serialize_by_alias=True, frozen=True
)


# --- Evidence files: the export the report is computed from ---


class Run(BaseModel):
    model_config = _CAMEL

    database_id: int = Field(
        validation_alias=AliasChoices("databaseId", "id"), description="The run's ID."
    )
    head_sha: str = Field(description="The commit on `main` the run built.")
    workflow_name: str = Field(
        validation_alias=AliasChoices("workflowName", "name"), description="The workflow's name."
    )
    event: str = Field(description="The event that started the run.")
    conclusion: Conclusion | None = Field(description="The run's result; null while it runs.")
    attempt: int = Field(
        validation_alias=AliasChoices("attempt", "run_attempt"),
        description="Above 1 after a re-run.",
    )
    created_at: datetime = Field(description="When the push created the run.")
    updated_at: datetime = Field(description="When the run last changed.")


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(description="The job's name.")
    conclusion: Conclusion | None = Field(description="The job's result; null while it runs.")
    started_at: datetime = Field(description="When the job started or was skipped.")
    completed_at: datetime | None = Field(description="When the job ended; null while it runs.")
    runner_name: str | None = Field(description="The job's runner; empty or null if it had none.")


class RunJobs(BaseModel):
    run: int = Field(description="The run's ID in the Actions API.")
    jobs: list[Job] = Field(description="The jobs of the run's latest attempt.")


class PullRequest(BaseModel):
    model_config = _CAMEL

    number: int = Field(description="The pull request's number.")
    author: str = Field(description="The author's login; `app/<name>` for a bot, as `gh` shows it.")
    first_commit_at: datetime = Field(description="The earliest author date of its commits.")
    merged_at: datetime = Field(description="When it was merged into `main`.")
    merge_commit: str = Field(description="The commit the merge put on `main`.")
    deployed_by: int = Field(description="The first green run at or after the merge commit.")


_RUNS = TypeAdapter(list[Run])
_RUN_JOBS = TypeAdapter(list[RunJobs])
_PULL_REQUESTS = TypeAdapter(list[PullRequest])


# --- GitHub REST payloads; `Run` and `Job` also read their own ---


class _RunsPage(BaseModel):
    total_count: int = Field(description="How many runs match, listed or not.")
    workflow_runs: list[Run] = Field(description="A page of the workflow's runs.")


class _JobsPage(BaseModel):
    jobs: list[Job] = Field(description="A page of the run's jobs.")


class GitHubUser(BaseModel):
    login: str = Field(description="The account's login; a bot's ends in `[bot]`.")
    type: str = Field(description="`User` or `Bot`.")

    def shown(self) -> str:
        # The committed evidence came from `gh pr list`, which shows a bot as `app/<name>`
        return f"app/{self.login.removesuffix('[bot]')}" if self.type == "Bot" else self.login


@dataclass(frozen=True)
class Merge:
    number: int
    author: str
    merged_at: datetime
    commit: str


class GitHubPull(BaseModel):
    number: int = Field(description="The pull request's number.")
    user: GitHubUser = Field(description="The pull request's author.")
    merged_at: datetime | None = Field(description="When it was merged; null if closed unmerged.")
    merge_commit_sha: str | None = Field(description="The commit the merge made.")

    def merge(self) -> Merge | None:
        if self.merged_at is None or self.merge_commit_sha is None:
            return None
        return Merge(self.number, self.user.shown(), self.merged_at, self.merge_commit_sha)


class _Parent(BaseModel):
    sha: str = Field(description="The parent commit.")


class _MainCommit(BaseModel):
    sha: str = Field(description="The commit.")
    parents: list[_Parent] = Field(description="Its parents, the first parent first.")


class _Author(BaseModel):
    date: datetime = Field(description="The commit's author date.")


class _CommitDetails(BaseModel):
    author: _Author = Field(description="The commit's git author.")


class _PullCommit(BaseModel):
    commit: _CommitDetails = Field(description="The commit's git data.")


def _workflow_runs(body: bytes) -> list[Run]:
    return _RunsPage.model_validate_json(body).workflow_runs


def _jobs(body: bytes) -> list[Job]:
    return _JobsPage.model_validate_json(body).jobs


_PULLS = TypeAdapter(list[GitHubPull])
_MAIN_COMMITS = TypeAdapter(list[_MainCommit])
_PULL_COMMITS = TypeAdapter(list[_PullCommit])


# --- Periods and the deployments of pull requests ---


@dataclass(frozen=True)
class Period:
    since: date
    until: date

    def __contains__(self, moment: datetime) -> bool:
        return _midnight(self.since) <= moment < self.end

    @property
    def end(self) -> datetime:
        return _midnight(self.until)

    @property
    def weeks(self) -> float:
        return (self.until - self.since).days / 7

    @property
    def label(self) -> str:
        return f"{self.since:%d.%m.%Y}{DASH}{self.until - timedelta(days=1):%d.%m.%Y}"


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(), KYIV)


def first_parent_order(head: str, first_parents: Mapping[str, str]) -> dict[str, int]:
    chain = [head]
    while (parent := first_parents.get(chain[-1])) is not None:
        chain.append(parent)
    return {sha: position for position, sha in enumerate(reversed(chain))}


def deployments(
    merges: Sequence[Merge], runs: Sequence[Run], order: Mapping[str, int]
) -> list[tuple[Merge, Run]]:
    green = sorted(
        (run for run in runs if run.conclusion == "success" and run.head_sha in order),
        key=lambda run: (order[run.head_sha], run.created_at),
    )
    positions = [order[run.head_sha] for run in green]
    deployed: list[tuple[Merge, Run]] = []
    for merge in merges:
        if merge.commit not in order:
            continue
        index = bisect_left(positions, order[merge.commit])
        if index < len(green):
            deployed.append((merge, green[index]))
    return deployed


# --- Metrics ---


@dataclass(frozen=True)
class Timing:
    created: datetime
    started: datetime
    ended: datetime

    @property
    def queue(self) -> timedelta:
        return self.started - self.created

    @property
    def run(self) -> timedelta:
        return self.ended - self.started


def timing(run: Run, jobs: Sequence[Job]) -> Timing | None:
    ran = [
        (job.started_at, ended)
        for job in jobs
        if bool(job.runner_name) and (ended := job.completed_at) is not None
    ]
    if not ran:
        return None
    return Timing(run.created_at, min(start for start, _ in ran), max(end for _, end in ran))


def _finished(run: Run, jobs: Sequence[Job]) -> datetime:
    measured = timing(run, jobs)
    return measured.ended if measured else run.updated_at


def recovery_times(runs: Sequence[Run], finished: Mapping[int, datetime]) -> list[timedelta]:
    times: list[timedelta] = []
    next_green: datetime | None = None
    for run in sorted(runs, key=lambda run: run.created_at, reverse=True):
        if run.conclusion == "success":
            next_green = finished[run.database_id]
        elif run.conclusion == "failure" and next_green is not None:
            times.append(next_green - finished[run.database_id])
    return times[::-1]


@dataclass(frozen=True)
class LeadTime:
    author: str
    total: timedelta
    before_merge: timedelta
    waiting: timedelta
    queue: timedelta
    run: timedelta


def lead_time(pull: PullRequest, deployed: Timing) -> LeadTime:
    return LeadTime(
        author=pull.author,
        total=deployed.ended - pull.first_commit_at,
        before_merge=pull.merged_at - pull.first_commit_at,
        waiting=max(deployed.created - pull.merged_at, timedelta()),
        queue=deployed.queue,
        run=deployed.run,
    )


def _median(durations: Sequence[timedelta]) -> timedelta:
    return timedelta(seconds=statistics.median(duration.total_seconds() for duration in durations))


@dataclass(frozen=True)
class Spread:
    count: int
    mean: timedelta
    median: timedelta


def spread(durations: Sequence[timedelta]) -> Spread | None:
    if not durations:
        return None
    return Spread(len(durations), sum(durations, timedelta()) / len(durations), _median(durations))


@dataclass(frozen=True)
class Part:
    label: str
    share: float
    median: timedelta


_PARTS: tuple[tuple[str, Callable[[LeadTime], timedelta]], ...] = (
    ("Before merge: writing, review, rework", lambda lead: lead.before_merge),
    ("After merge, waiting for a green `main`", lambda lead: lead.waiting),
    ("Queue before the first job", lambda lead: lead.queue),
    ("Run", lambda lead: lead.run),
)


def split(leads: Sequence[LeadTime]) -> list[Part]:
    total = sum((lead.total for lead in leads), timedelta())
    if not total:
        return []
    parts: list[Part] = []
    for label, part in _PARTS:
        durations = [part(lead) for lead in leads]
        parts.append(Part(label, sum(durations, timedelta()) / total, _median(durations)))
    return parts


def queue_share(leads: Sequence[LeadTime]) -> float | None:
    queue = sum((lead.queue for lead in leads), timedelta())
    ci = queue + sum((lead.run for lead in leads), timedelta())
    return queue / ci if ci else None


@dataclass(frozen=True)
class Summary:
    period: Period
    runs: int
    green: int
    red: int
    cancelled: int
    team_green: int
    lead: Spread | None
    team_lead: Spread | None
    recovery: Spread | None
    unrecovered: int
    parts: list[Part]
    queue_share: float | None

    @property
    def change_fail_rate(self) -> float | None:
        completed = self.green + self.red
        return self.red / completed if completed else None


def summarise(
    period: Period,
    runs: Sequence[Run],
    jobs: Mapping[int, Sequence[Job]],
    pulls: Sequence[PullRequest],
) -> Summary:
    counted = [run for run in runs if run.created_at in period]
    recovering = [
        *counted,
        *(run for run in runs if run.conclusion == "success" and run.created_at >= period.end),
    ]
    timings = {run.database_id: timing(run, jobs.get(run.database_id, [])) for run in counted}
    finished = {
        run.database_id: _finished(run, jobs.get(run.database_id, [])) for run in recovering
    }
    green = [run for run in counted if run.conclusion == "success"]
    red = sum(run.conclusion == "failure" for run in counted)
    recoveries = recovery_times(recovering, finished)
    leads = [
        lead_time(pull, deployed)
        for pull in pulls
        if (deployed := timings.get(pull.deployed_by)) is not None
    ]
    released = {pull.merge_commit for pull in pulls if pull.author == RELEASE_BOT}
    return Summary(
        period=period,
        runs=len(counted),
        green=len(green),
        red=red,
        cancelled=sum(run.conclusion == "cancelled" for run in counted),
        team_green=sum(run.head_sha not in released for run in green),
        lead=spread([lead.total for lead in leads]),
        team_lead=spread([lead.total for lead in leads if lead.author != RELEASE_BOT]),
        recovery=spread(recoveries),
        unrecovered=red - len(recoveries),
        parts=split(leads),
        queue_share=queue_share(leads),
    )


# --- Report ---


def _duration(value: timedelta) -> str:
    if value < timedelta(hours=1):
        return f"{value / timedelta(minutes=1):.0f} min"
    return f"{value / timedelta(hours=1):.1f} h"


def _spread(value: Spread | None) -> str:
    if value is None:
        return DASH
    return f"median **{_duration(value.median)}**, mean {_duration(value.mean)} (n = {value.count})"


def render(summary: Summary) -> str:
    weeks = summary.period.weeks
    rate = summary.change_fail_rate
    fail_rate = (
        f"{summary.red} / {summary.green + summary.red} = **{rate:.1%}**"
        if rate is not None
        else DASH
    )
    queue = summary.queue_share
    queue_vs_run = f"{queue:.0%} queue, {1 - queue:.0%} run" if queue is not None else DASH
    unrecovered = f"; not yet recovered: {summary.unrecovered}" if summary.unrecovered else ""
    lines = [
        "# Computed DORA Metrics",
        "",
        f"The `CI/CD` push runs on `main` created {summary.period.label}, Kyiv time, by the",
        "definitions in [`dora-summary.md`](dora-summary.md), from [`evidence/`](evidence/).",
        "Generated by `.github/scripts/dora_metrics.py report`; run it again instead of editing.",
        "",
        "| Metric | Result |",
        "| --- | --- |",
        (
            f"| Runs | {summary.runs}: {summary.green} green, {summary.red} red, "
            f"{summary.cancelled} cancelled |"
        ),
        (
            f"| Deployment frequency | {summary.green} / {weeks:.1f} weeks = "
            f"**{summary.green / weeks:.1f} a week**; {summary.team_green / weeks:.1f} without "
            "the release bot |"
        ),
        (
            f"| Change lead time | {_spread(summary.lead)}; without the release bot "
            f"{_spread(summary.team_lead)} |"
        ),
        f"| Change fail rate | {fail_rate} |",
        f"| Failed deployment recovery time | {_spread(summary.recovery)}{unrecovered} |",
        "",
        "## Where the Lead Time Goes",
        "",
        "| Part of the lead time | Share of all lead time | Median per pull request |",
        "| --- | ---: | ---: |",
        *(
            f"| {part.label} | {part.share:.1%} | {_duration(part.median)} |"
            for part in summary.parts
        ),
        "",
        f"Queue vs run, of the time CI adds to the lead time: {queue_vs_run}.",
    ]
    return "\n".join(lines) + "\n"


# --- Commands ---


type Get = Callable[[str], bytes]


def github(token: str) -> Get:
    def get(path: str) -> bytes:
        request = urllib.request.Request(
            f"{GITHUB_API}/{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return bytes(response.read())

    return get


def _paged[T](path: str, get: Get, parse: Callable[[bytes], list[T]]) -> list[T]:
    items: list[T] = []
    separator = "&" if "?" in path else "?"
    page = 1
    while True:
        chunk = parse(get(f"{path}{separator}per_page={PAGE_SIZE}&page={page}"))
        items.extend(chunk)
        if len(chunk) < PAGE_SIZE:
            return items
        page += 1


class RunLimitError(Exception):
    pass


def runs_created(first: date, last: date, get: Get) -> list[Run]:
    """The runs created on the Kyiv days `first` to `last`; RunLimitError if GitHub hides some."""
    if first > last:
        return []
    end = _midnight(last + timedelta(days=1)) - timedelta(seconds=1)
    window = f"{_midnight(first).isoformat()}..{end.isoformat()}"
    path = f"{RUNS}&created={urllib.parse.quote(window, safe='')}"
    count = _RunsPage.model_validate_json(get(f"{path}&per_page=1")).total_count
    if count < RUN_LIMIT:
        return _paged(path, get, _workflow_runs)
    if first == last:
        message = (
            f"{count} runs were created on {first:%d.%m.%Y}, and GitHub lists at most "
            f"{RUN_LIMIT} for one query"
        )
        raise RunLimitError(message)
    middle = first + timedelta(days=(last - first).days // 2)
    return [*runs_created(middle + timedelta(days=1), last, get), *runs_created(first, middle, get)]


def exported_runs(runs: Sequence[Run], period: Period) -> list[Run]:
    """The runs of the period, and the green run after it that recovers a red run at its end."""
    ordered = sorted(runs, key=lambda run: run.created_at)
    in_period = [run for run in ordered if run.created_at in period]
    completed = [run.conclusion for run in in_period if run.conclusion in ("success", "failure")]
    if not completed or completed[-1] == "success":
        return in_period
    recovery = next(
        (run for run in ordered if run.conclusion == "success" and run.created_at >= period.end),
        None,
    )
    return in_period if recovery is None else [*in_period, recovery]


def write_evidence(path: Path, rows: Sequence[BaseModel]) -> None:
    path.write_text(
        "[\n" + ",\n".join(row.model_dump_json() for row in rows) + "\n]\n", encoding="utf-8"
    )


def fetch(period: Period, get: Get) -> None:
    history = _paged("commits?sha=main", get, _MAIN_COMMITS.validate_json)
    order = first_parent_order(
        history[0].sha, {commit.sha: commit.parents[0].sha for commit in history if commit.parents}
    )
    merges = [
        merge
        for pull in _paged("pulls?state=closed&base=main", get, _PULLS.validate_json)
        if (merge := pull.merge()) is not None
    ]
    # A merge before the period may have been deployed by a run before it; a red run at its end
    # recovers after it
    first = min([period.since, *(merge.merged_at.astimezone(KYIV).date() for merge in merges)])
    runs = runs_created(first, datetime.now(KYIV).date(), get)
    pulls = [
        PullRequest(
            number=merge.number,
            author=merge.author,
            first_commit_at=min(
                commit.commit.author.date
                for commit in _paged(
                    f"pulls/{merge.number}/commits", get, _PULL_COMMITS.validate_json
                )
            ),
            merged_at=merge.merged_at,
            merge_commit=merge.commit,
            deployed_by=run.database_id,
        )
        for merge, run in sorted(deployments(merges, runs, order), key=lambda pair: pair[0].number)
        if run.created_at in period
    ]
    exported = exported_runs(runs, period)
    jobs = [
        RunJobs(
            run=run.database_id, jobs=_paged(f"actions/runs/{run.database_id}/jobs", get, _jobs)
        )
        for run in exported
    ]
    write_evidence(EVIDENCE / "runs.json", exported)
    write_evidence(EVIDENCE / "jobs.json", jobs)
    write_evidence(EVIDENCE / "pull-requests.json", pulls)
    sys.stdout.write(f"Wrote {len(exported)} runs and {len(pulls)} pull requests to {EVIDENCE}\n")


def report(period: Period, ci_cd: Path) -> None:
    evidence = ci_cd / "evidence"
    runs = _RUNS.validate_json((evidence / "runs.json").read_bytes())
    run_jobs = _RUN_JOBS.validate_json((evidence / "jobs.json").read_bytes())
    pulls = _PULL_REQUESTS.validate_json((evidence / "pull-requests.json").read_bytes())
    summary = summarise(period, runs, {entry.run: entry.jobs for entry in run_jobs}, pulls)
    (ci_cd / "dora-metrics.md").write_text(render(summary), encoding="utf-8")
    sys.stdout.write(f"Wrote {ci_cd / 'dora-metrics.md'}\n")


class _Arguments(argparse.Namespace):
    command: Literal["fetch", "report"]
    since: date
    until: date


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="DORA metrics of the CI/CD runs on main, by the Lab 10 definitions."
    )
    parser.add_argument(
        "command",
        choices=["fetch", "report"],
        help="fetch: export the run history from GitHub into docs/ci-cd/evidence (needs "
        "GITHUB_TOKEN); report: compute docs/ci-cd/dora-metrics.md from that export",
    )
    parser.add_argument("--since", type=date.fromisoformat, required=True, help="first day, Kyiv")
    parser.add_argument(
        "--until", type=date.fromisoformat, required=True, help="day after the last"
    )
    arguments = parser.parse_args(argv, namespace=_Arguments())
    if arguments.until <= arguments.since:
        parser.error("--until must be after --since")
    period = Period(arguments.since, arguments.until)
    if arguments.command == "report":
        report(period, CI_CD)
        return
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        sys.exit("Set GITHUB_TOKEN, for example GITHUB_TOKEN=$(gh auth token)")
    try:
        fetch(period, github(token))
    except urllib.error.HTTPError as error:
        sys.exit(f"HTTP {error.code} from {error.url}")
    except RunLimitError as error:
        sys.exit(str(error))
    except (urllib.error.URLError, TimeoutError, ValidationError) as error:
        sys.exit(f"Fetching from GitHub failed: {type(error).__name__}")


if __name__ == "__main__":
    main()
