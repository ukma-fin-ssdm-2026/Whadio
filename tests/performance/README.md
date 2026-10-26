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

## Run k6 from Docker

In another PowerShell terminal, set credentials without placing the password in shell history:

```powershell
$env:WHADIO_EMAIL = "performance@whadio.dev"
$env:WHADIO_PASSWORD = Read-Host "Whadio password"
$scriptDir = (Resolve-Path ".\tests\performance").Path

docker run --rm `
  --add-host host.docker.internal:host-gateway `
  -e BASE_URL=http://host.docker.internal:3000 `
  -e WHADIO_EMAIL `
  -e WHADIO_PASSWORD `
  --mount "type=bind,source=$scriptDir,target=/scripts,readonly" `
  grafana/k6:0.54.0 run /scripts/test_lists.js

Remove-Item Env:WHADIO_PASSWORD
```

Run the command from the repository root. Resolving the directory before starting Docker makes a
missing local script fail in PowerShell instead of appearing as a missing `/scripts/test_lists.js`
module inside k6. `host.docker.internal` lets the container reach the API on the host;
`--add-host` also supplies that name on Linux Docker Engine.

## Record the result

Preserve the terminal summary and record:

- date, Whadio commit and k6 image version;
- operating system, CPU and RAM;
- one-worker server command and database location;
- number of workspaces and meetings visible to the account;
- `http_req_duration` p95 and `http_req_failed` for each tagged endpoint;
- pass/fail against 200 ms, plus any environmental limitation.

The result is valid only when both endpoint-specific duration thresholds and both error-rate
thresholds pass. Setup traffic is intentionally not evidence for either endpoint.

## AI Usage

This k6 scenario and runbook were prepared with OpenAI Codex 5.6 from TC-NFR-02, QA-1 and the current Whadio API contract. Zlata owns the test execution, environment record and interpretation.
