# DORA Report

The four DORA metrics for Whadio over three weeks, 20.10–09.11.2026, computed from the runs in
[`metrics-raw.md`](metrics-raw.md).

## Definitions

- **Deployment:** a green run of the `CI/CD` workflow on `main`. Nothing is deployed to production
  yet, so every green build on `main` counts as releasable (continuous delivery). The figures are
  an approximation of DORA's.
- **Workflows counted:** `CI/CD` only. `Release` also runs on pushes to `main` but only publishes
  versions, and `Commit messages` runs on pull requests only.
- **Runs:** 130 runs: 94 green, 16 red and 20 cancelled. Our workflow keeps one waiting run on
  `main`, so a newer push cancels a queued run. Cancelled runs are not completed runs; their pull
  requests count towards the next green run.
- **Lead time:** for each of the 157 pull requests that reached a green run in the period, from its
  first commit to the end of that run. 27 of them were merged on 18–19.10, while `main` was red.
- **Recovery:** from the end of each red run to the end of the next green run, even one after the
  period; a red run with no green run after it yet counts as not yet recovered.

## Metrics

| Metric | Formula | Result | Level (by the median) → DORA 2025 share at this level or better |
| --- | --- | :---: | --- |
| Deployment frequency | green runs / weeks | 94 / 3 = **31 a week** (4.5 a day) | on demand → 16.2% |
| Change lead time | first PR commit → end of the green run with it | median **25.8 h**, mean 53.3 h | a day to a week → 56.4% |
| Change fail rate | red / completed runs | 16 / 110 = **14.5%** | 8–16% → 62.2% |
| Failed deployment recovery time | red run → next green run | median **14.2 h**, mean 50.4 h (16 runs) | under a day → 56.5% |

- The 18 release-bot changes count as deployments; without them the frequency is 25 a week and the
  median lead time 31.5 h.
- 6 of the 21 days had no green run: 20–24.10, while `main` was red (nobody merged on 22–24.10),
  and 06.11, with no merges.

| Indicator (CircleCI) | Target | CircleCI data, 2025 | Whadio |
| --- | :---: | :---: | :---: |
| Runs on `main` that succeed | 90% | 70.8% | 85.5% |
| Time to get `main` green again | ≤ 60 min | 59.2 min (median) | 14.2 h (median) |
| Workflow duration | ≤ 10 min | 2.2 min (median) | 9.5 min (median, green runs) |

## Where the Lead Time Goes

| Part of the lead time | Share of all lead time | Median per PR |
| --- | ---: | ---: |
| Before merge: writing, review, rework | 38.4% | 10.9 h |
| After merge, waiting for a green `main` | 60.5% | 0 min |
| Queue before the first job | 0.6% | 1 min |
| Run | 0.5% | 9 min |

- **Queue vs run:** of the time CI itself adds, the queue is 56% and the run 44%. 73% of that
  queue is one run on the midterm eve (row 75), which waited 4.4 h with 9 pull requests in it.
- **Inside runs:** 40% of the run time is also waiting, for a free runner between jobs.
- **When the queue builds:** most runs start at once (median queue 0 min). All but one of the runs
  that waited 15 min or more fell in the four days before the midterm. On 01.11 our runs waited
  15.6 h for runners in total, and one 41-minute run took 5.7 h.

## Reading the Pairs

- **Speed:** we deploy several times a day, and CI adds about 10 minutes, 1% of the lead time. A
  change still takes 26 h (median); across all changes, 60% of the time is waiting for a red `main`
  to go green.
- **Stability:** the 14.5% fail rate overstates our defects. One of the 16 red runs was a defect of
  the change; 14 came from outside (GitHub billing, new advisories in locked packages) and one was
  a flaky test.
- **Together:** the high frequency hides the cost of a red `main`. Merges went on while it was red,
  and it stayed red for days, 5.5 at worst. Since the audit stopped failing runs (01.11) and `CI
  passed` became a required check (02.11), `main` has had no red run in 8 days.

## Red Runs on `main`

A blameless review of each episode of consecutive red runs; the numbers are the rows of
[`metrics-raw.md`](metrics-raw.md).

| Episode | Runs | What failed | Why the PR checks missed it | Check to add |
| --- | --- | --- | --- | --- |
| 20.10–25.10, **5.5 d** (7.3 d from 18.10) | 1–7, 10–12 | GitHub billing stopped the hosted runners; after the move to the course runners (#117), `uv audit` failed on advisories in locked packages. Fixed by #148. | Not a defect of the change: every PR failed the same way, and `main` required no check | Done: the audit warns and `CI passed` is required |
| 30.10, **9.1 h** | 34 | The generated API types were stale: #193 was merged after #199 had added their check. Fixed by #200. | The PR's checks ran on an outdated base | None: requiring up-to-date branches would rerun every open PR's CI after each merge |
| 30.10–31.10, **20.4 h** | 40–43 | A new `joserfc` advisory failed the audit. Fixed by #223. | Not a defect of the change: the advisory failed every run | As in the first episode |
| 01.11, **24 min** | 60 | A SPA test that timed the transcript poll failed; the next run passed with no frontend change. #241 replaced the timing with a wait. | It depends on timing and passed in the PR | CI retries a failed test once and flags it |

## Root Causes

**Technical**

- A blocking dependency audit failed runs on someone else's schedule: 10 of 16 red runs.
- Four runners serve the whole course, and each of our runs takes up to six jobs. The split into
  parallel jobs (01.11) kept the run time (9.0 → 9.5 min) but doubled its runner time (8.9 → 17.2
  min).
- Documentation-only pushes run the whole pipeline: 13 runs.
- A timing-dependent test (fixed).

**Organisational**

- Pull requests were merged while `main` was red, until 02.11.
- Merges bunch before deadlines: 35% of the runs fell in the four days before the midterm. We
  accept this, since we work around other courses.
- A pull request waits 5.8 h (median) for its first review, half of the time it is open.
- Pull requests were merged without first taking in the latest `main`.

## Improvement Backlog

| Metric | Problem | Root cause | Action | Owner |
| :--- | :--- | :--- | :--- | :--- |
| Deployment frequency | Every figure is an approximation; 18 of 94 deployments are release commits | The application is not deployed anywhere yet, so a green run stands in for a deployment | Deploy the application to its public server from every green `main` run, and measure the four metrics from those deployments | `@Hukyl` |
| Deployment frequency | Approved pull requests wait to be merged: 10 of 112 waited over 12 h | The author has to come back to merge | Allow auto-merge, so an approved pull request merges as soon as its checks pass | `@v-missirova` |
| Change lead time | A pull request waits 5.8 h (median) for its first review, half of the time it is open | Reviews happen when someone remembers | A daily message in the team chat listing the pull requests that wait for review | `@SquidBow` |
| Change lead time | Waits of up to 5.7 h on 01.11 | Six jobs per run on four runners shared by the course | Skip CI for documentation-only pushes | `@t-zlata` |
| Lead time, recovery time | 60% of all lead time is waiting for a green `main`; recovery median 14.2 h | Merges went on while `main` was red | Done: `CI passed` must pass before a merge (02.11). `main` has had no red run since 01.11 | `@Hukyl` |
| Recovery time | A red `main` waited for whoever looked next | Nothing tells the team that `main` is red | Post to the team chat when a run on `main` turns red | `@v-missirova` |
| Change fail rate | 10 of 16 red runs came from the audit | A new advisory failed every run, whatever the change | Done: the audit warns instead of failing (01.11) | `@Hukyl` |
| Change fail rate | A flaky test turned `main` red | It moved fake timers by a fixed step, and a slow answer fell behind | Done: fixed in #241. CI retries a failed test once and flags the tests that passed only on retry | `@t-zlata` |

## Dashboard

The metrics table above, with two charts. Completed runs on `main` by start day; the red part is
the red runs.

```mermaid
%%{init: {"themeVariables": {"xyChart": {"plotColorPalette": "#2da44e, #cf222e"}}}}%%
xychart-beta
    title "Runs on main per day, 20.10–09.11"
    x-axis [20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    y-axis "Runs" 0 --> 16
    bar [4, 2, 0, 0, 0, 5, 9, 6, 1, 3, 8, 6, 14, 0, 16, 5, 6, 0, 5, 14, 6]
    bar [4, 2, 0, 0, 0, 4, 0, 0, 0, 0, 4, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0]
```

Minutes our runs waited for a runner, before and between jobs, by start day.

```mermaid
%%{init: {"themeVariables": {"xyChart": {"plotColorPalette": "#bf8700"}}}}%%
xychart-beta
    title "Waiting for a runner, minutes per day"
    x-axis [20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    y-axis "Minutes" 0 --> 1000
    line [0, 0, 0, 0, 0, 3, 1, 1, 0, 50, 263, 78, 935, 0, 67, 13, 31, 0, 46, 39, 32]
```

**Key finding.** CI is not what slows us down: the queue and the run are 1% of the lead time. A
red `main` is: waiting for it to go green is 60% of all lead time, and 14 of the 16 red runs came
from outside our code.

**Action for next week.** A daily message in the team chat listing the pull requests that wait for
review.

## What Pain Did These Metrics Reveal in Our Team?

- **A red `main` stopped everyone.** Nothing could be deployed for 5.5 days, and the 27 pull
  requests merged on 18–19.10 waited for a green run until 25.10. Waiting for a green `main` is 60%
  of all lead time.
- **We fixed what was not ours.** 14 of the 16 red runs came from GitHub billing and new
  advisories, and two pull requests did nothing but upgrade flagged packages (#148, #223).
- **Feedback comes slowly.** A pull request waits 5.8 h (median) for its first review, and 19
  stayed open for over two days.
- **Deadlines crowd the runners.** On the eve of the midterm our runs waited 15.6 h for runners in
  total, and the midterm commit sat 4.4 h in the queue.
- **CI itself did not hurt:** it adds about 10 minutes, 1% of the lead time.

## Bonuses

### 1. Metrics script

A script computes the four metrics by the definitions above, with the queue and the run apart, for
any period. `fetch` exports the run history from the GitHub API into [`evidence/`](evidence/), and
`report` computes [`dora-metrics.md`](dora-metrics.md) from that export alone. The dates are Kyiv
time, and `--until` is the day after the period's last day:

```bash
GITHUB_TOKEN=$(gh auth token) uv run python .github/scripts/dora_metrics.py fetch --since 2026-10-20 --until 2026-11-10
uv run python .github/scripts/dora_metrics.py report --since 2026-10-20 --until 2026-11-10
```

**Discrepancies with Stage 2:** none in the data or the figures, since Stage 2 used a prototype of
this script. On 17.11 `fetch` wrote the three evidence files byte for byte as committed, and every
row of [`metrics-raw.md`](metrics-raw.md) matches the script's queue, run and end times. Only the
rounding differs: 31 and 25 deployments a week above, 31.3 and 25.3 in the script's output.

## AI Usage

The run data was collected with `gh` and analysed, and the documents, the exported data and the
metrics script were drafted, with Claude Code; Andrii Shalaiev reviewed them.
