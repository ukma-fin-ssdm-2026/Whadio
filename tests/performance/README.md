# Performance tests

`test_lists.js` measures the two API requests behind the meeting and workspace list views.
It implements TC-NFR-02 with two isolated stages against one uvicorn worker:

| Stage | Load | Duration | Pass criteria |
|---|---:|---:|---|
| `GET /api/v1/workspaces?limit=100` | 50 VUs | 30 s | p95 <= 200 ms, no failed requests |
| `GET /api/v1/workspaces/{workspace_id}/meetings?limit=100` | 50 VUs | 30 s | p95 <= 200 ms, no failed requests |

The one-second pause between iterations models repeated page reads without adding time to the HTTP
latency metric. Sign-in and workspace discovery happen once in `setup()` and are excluded from the
endpoint thresholds. Measured list requests time out after four seconds, before the five-second
scenario grace period ends, so a hanging request is recorded as a failure instead of disappearing
from the result. Use a dedicated local account and non-sensitive seed data.

## Prepare Whadio

For the bundled database, use the PostgreSQL host from `.env.example` and the application pool defaults.

From the repository root, start the infrastructure, apply migrations and create a browser account:

```powershell
uv run task infra:up
uv run task db:upgrade
uv run whadio dev-user --email performance@whadio.dev
uv run whadio web --host 0.0.0.0
```

`uv run whadio web --host 0.0.0.0` starts one uvicorn worker on port 3000 and exposes it to the
Docker bridge used by k6. Keep it running in its own terminal. The account always has a personal
workspace; add representative meetings before measuring if the result is intended to characterize
a populated list rather than an empty one.

## Compare native Windows and Docker k6

From the repository root, run [native k6 0.54.0](https://github.com/grafana/k6/releases/tag/v0.54.0)
and the matching Docker image against the same Whadio process, account, and data.

```powershell
$env:WHADIO_EMAIL = "performance@whadio.dev"
$env:WHADIO_PASSWORD = [System.Net.NetworkCredential]::new(
  "", (Read-Host "Whadio password" -AsSecureString)
).Password
$scriptPath = (Resolve-Path ".\tests\performance\test_lists.js" -ErrorAction Stop).Path
$scriptDir = Split-Path -Parent $scriptPath
$outputDir = (New-Item -ItemType Directory -Path (Join-Path $env:TEMP "whadio-perf-$(Get-Date -Format yyyyMMdd-HHmmss)")).FullName

$env:BASE_URL = "http://127.0.0.1:3000"
k6 run --out "json=$outputDir/windows.json" "$scriptPath"

docker run --rm `
  --add-host host.docker.internal:host-gateway `
  -e BASE_URL=http://host.docker.internal:3000 `
  -e WHADIO_EMAIL `
  -e WHADIO_PASSWORD `
  --mount "type=bind,source=$scriptDir,target=/scripts,readonly" `
  --mount "type=bind,source=$outputDir,target=/results" `
  grafana/k6:0.54.0 run --out json=/results/docker.json /scripts/test_lists.js

Remove-Item Env:WHADIO_PASSWORD, Env:BASE_URL
```

`Resolve-Path` reports a missing script in PowerShell before k6 starts.
`--add-host` supplies `host.docker.internal` on Linux Docker Engine so k6 can reach the host API.

## Classify failed requests

In either JSON file, filter `http_req_failed` points with `data.value = 1` and endpoint
`workspace-list` or `meeting-list`. The samples include a timestamp and the `status`,
`error_code`, and `error` tags when present. Codes 1050 and 1211 indicate timeouts,
statuses 400–599 indicate HTTP errors, and other failures with status 0 indicate transport errors.
Keep raw output local because it includes workspace IDs.

## Record the result

Keep both k6 summaries and JSON files even if a threshold fails. Record:

- date, Whadio commit, k6 and Docker versions, and host and database configuration;
- workspace and meeting counts in the test data;
- per endpoint and run mode, p95, request count, failure rate, and failure categories.

A completed run passes only when both endpoint-specific duration, error-rate and HTTP
200 check thresholds pass.

## AI Usage

This k6 scenario and runbook were prepared with OpenAI Codex 5.6 from TC-NFR-02, QA-1 and the current Whadio API contract. Zlata owns the test execution, environment record and interpretation.
OpenAI Codex assisted with the diagnostic workflow for issue #162.
