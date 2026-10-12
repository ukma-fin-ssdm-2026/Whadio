# Static Analysis

Commit analysed: `2d2c949` on `main` (PR #68 merged).

## What runs and where

Every tool below runs in the pre-commit hook (`.pre-commit-config.yaml`) and again in CI (`.github/workflows/ci.yml`). `uv run task check` runs the same set locally. Inline suppressions (`# noqa`, `# nosec`, `# type: ignore`, ...) are refused by the `no-suppressions` hook, so a finding has to be fixed in the code or excepted in `pyproject.toml` with a reason.

| Tool | Layer | What it checks |
|---|---|---|
| Bandit 1.9.4 | security | Python security issues: hardcoded secrets, injection, unsafe calls |
| ruff (`select = ["ALL"]`) | style, bugs, security | PEP 8, formatting, and the flake8-bandit `S` rules |
| ty, basedpyright | types | strict typing, no `Any` or `cast` escape hatches |
| import-linter | architecture | modules call only the modules below them in the component diagram |
| gitleaks, detect-private-key | secrets | keys and passwords in staged changes; `task audit` scans the whole history |
| uv audit, Dependabot | dependencies | known vulnerabilities in locked packages |
| deptry | dependencies | unused, missing and misplaced dependencies |
| zizmor, actionlint | CI | unsafe GitHub Actions workflows |

## Bandit results

Command: `uv run bandit -c pyproject.toml -r src`

- **Coverage:** all of `src/`, 182 Python files, 17 678 lines, tests included. No file is skipped.
- **Configuration:** one exception in `pyproject.toml`: `B101` (`assert`) is skipped in `*/test_*.py`, because pytest asserts with `assert`.
- **Result on `2d2c949`:** no issues, at any severity.

### What the hook stopped

While building sign-in for PR #68, Bandit `B105` (hardcoded password string) and ruff `S105` stopped the commit: the session tests compared against literal passwords such as `"wrong"`. They are test fixtures, not real credentials, but the rule cannot tell, and a literal password in the repository is how real ones get committed too.

**Fixed:** every test password is now generated per run with `uuid4().hex` (`accounts/test_services.py`, `api/accounts/test_routes_sessions.py`, `api/accounts/test_routes_workspaces.py`).

## Documented vulnerability: forged processing results

Bandit found nothing in the current code, so, as the lab allows, this takes a threat from `docs/architecture/threat-model.md` and shows how the code stands against it. It is also a real defect: the code review of PR #68 found it before the fix.

- **Threat:** `R-06`, RabbitMQ and processing jobs, Tampering: "A forged or replayed queue message marks processing as successful, attaches output to the wrong meeting". Related: `R-14`, the ASR worker must not read `notes.requests`.
- **Found by:** manual code review (PR #68). No static tool can see it: the code was correct Python, the flaw was in who it trusted.
- **What was wrong:** the web service accepted every message on the `processing.results` queue. Anyone able to publish to the broker (another service, a leaked worker password) could send "transcript ready" for any meeting, and it would be saved as that meeting's transcript. The notes worker's login could also fake transcripts.
- **Why it is a risk:** transcripts and notes are the product. A forged one is silently wrong content in someone's meeting, and later notes use it as context.
- **Fix** (commit `2d53994` in PR #68):
  - each worker gets its own broker user with least privilege (`infra/rabbitmq/users.sh`): it reads only its own job queue and writes only results, so the ASR user cannot read notes jobs, which carry whole transcripts;
  - RabbitMQ stamps every message with the publishing user, and a client cannot fake that field. `handle_delivery` (`src/whadio/processing/consumer.py`) drops messages from any other user, and `WorkerUsers.publisher_of` accepts transcript results only from the ASR user and notes only from the notes user;
  - `ProcessingService.handle` (`src/whadio/processing/services.py`) also drops a result whose meeting, job type or job state does not match the job, so replayed or late messages change nothing.
- **Regression tests** (`src/whadio/processing/test_consumer.py`):
  - `test_result_from_an_unexpected_publisher_is_rejected_without_requeue`
  - `test_result_without_a_publisher_is_rejected_without_requeue`
  - `test_notes_start_from_the_asr_worker_is_rejected_without_requeue`
  - `test_transcription_result_from_the_notes_worker_is_rejected_without_requeue`
  - `test_dead_letter_from_an_unexpected_publisher_fails_no_job`
- **Accepted:** whoever holds a worker's own password can still forge that worker's kind of result. Network isolation of the broker (`R-13`) limits who can reach it at all.

## AI Usage

Drafted with Claude Code (Claude Opus 5.5) from the repository's configuration, a Bandit run on `2d2c949` and the PR #68 review; checked by Denys Zabiiaka.
