# Evidence

The data behind [`metrics-raw.md`](../metrics-raw.md), exported from GitHub on 10.11.2026 and
limited to the period 20.10–09.11.2026. Times are in UTC.

| File | What it holds | Source |
| --- | --- | --- |
| `runs.json` | The 130 `CI/CD` runs on `main` | `gh run list --workflow ci.yml --branch main --json databaseId,headSha,workflowName,event,conclusion,attempt,createdAt,updatedAt` |
| `jobs.json` | Each run's jobs with their start, end and runner, for the queue and run times | `gh api repos/ukma-fin-ssdm-2026/Whadio/actions/runs/<run>/jobs` |
| `pull-requests.json` | The 157 pull requests deployed in the period: first commit, merge, and the green run that deployed it | `gh pr list --state merged --base main` and `gh api repos/ukma-fin-ssdm-2026/Whadio/pulls/<number>/commits` |

The 20 cancelled runs have no jobs, and `runner_name` is empty for the four runs that GitHub never
started because of billing.
