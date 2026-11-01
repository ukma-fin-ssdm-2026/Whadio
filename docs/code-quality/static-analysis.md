# Static Analysis

Commit analysed: `2d2c949` on `main` (PR #68 merged).

## What runs and where

Every tool below runs in CI (`.github/workflows/ci.yml`), and `.pre-commit-config.yaml` sets which of them also run in the commit and push hooks. `uv run task check` and `uv run task audit` run the same set locally, and `uv run task ci` runs every CI job. Inline suppressions (`# noqa`, `# nosec`, `# type: ignore`, `biome-ignore`, ...) are refused by the `no-suppressions` hook, so a finding has to be fixed in the code or excepted in `pyproject.toml` or `frontend/biome.jsonc` with a reason.

| Tool | Layer | What it checks |
|---|---|---|
| Bandit 1.9.4 | security | Python security issues: hardcoded secrets, injection, unsafe calls |
| ruff (`select = ["ALL"]`) | style, bugs, security | PEP 8, formatting, and the flake8-bandit `S` rules |
| Biome 2.6.3 | frontend and extension style, bugs | formatting, import order and the recommended lint rules, React hooks and accessibility included; warnings fail too |
| ty, basedpyright | types | strict typing, no `Any` or `cast` escape hatches |
| TypeScript 5.9 (`tsc`, strict) | frontend types | strict typing of the `.ts`/`.tsx` files, `noUncheckedIndexedAccess` included |
| import-linter | architecture | modules call only the modules below them in the component diagram |
| gitleaks, detect-private-key | secrets | keys and passwords in staged changes; `task check` scans the whole history |
| uv audit, Dependabot | dependencies | known vulnerabilities in locked packages; a warning, not a failure |
| npm audit | dependencies | known high and critical vulnerabilities in the frontend's packages, the build tools included; runs in `task audit`, as a warning |
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

## Further findings

### Signed recording links written to the worker logs

- **What.** httpx2 logs every request URL at `INFO`, the workers' default level. The ASR worker
  downloads each recording through a presigned link, so every link, signature included, went to
  its log.
- **Found by.** Reading the ASR worker's log. No static analyzer sees this: it is how a
  third-party library behaves at runtime.
- **Why it is a risk.** Anyone who can read the logs can download the recording until the link
  expires. It breaks the threat model's rule that logs carry no tokens or recordings ("Design
  Constraints Derived From This Model", and `R-03`).
- **Fixed** in the pull request "keep signed recording links out of the logs":
  `configure_logging` raises the `httpx2` logger to `WARNING` (`src/whadio/shared/logs.py`).
- **Regression test.** `src/whadio/shared/test_logs.py::test_logged_requests_leave_out_signed_urls`
  fails without the fix, because the captured log contains `X-Amz-Signature=secret`, and passes
  with it.

### Validation errors echoed the rejected password

- **What.** Every validation error put the rejected input into `provided_value`
  (`src/whadio/api/core/errors.py`). A sign-in with a password over 128 characters answered `422`
  with the whole password in the response body.
- **Found by.** Another team's AI-assisted review of our code (`review-report.md`, "Feedback on
  our code"). Bandit and Ruff have no rule for it (CWE-209, CWE-532).
- **Why it is a risk.** Browser developer tools, reverse proxies and error trackers keep response
  bodies, so the password ends up stored outside the database.
- **Fixed** in the pull request "stop echoing request bodies in validation errors":
  only query and path values are echoed now. The threat model already keeps tokens out of URLs,
  while a body, a header or a cookie can carry a password or a token. `docs/api/api-design.md`,
  "Envelope", states the rule.
- **Regression tests** in `src/whadio/api/core/test_errors.py`:
  - `test_invalid_password_is_left_out_of_the_validation_error` and
    `test_invalid_body_field_is_named_without_its_value` fail without the fix and pass with it;
  - `test_invalid_query_parameter_is_echoed` and `test_invalid_path_parameter_is_echoed` keep the
    echo where it is safe.

### Found and fixed in the review of the backend pull request

- **Hardcoded demo credentials** (ruff `S105`).
  - The Lab 4 stub kept its demo password and tokens as literals in
    `api/accounts/fixtures.py`, under an exception in `pyproject.toml`. That was acceptable while
    the API stored nothing.
  - The first version of the backend pull request seeded that account into the real database on every start, which
    gave Owner access on any deployment. The review had the seed, the fixtures and the
    exceptions removed.
  - Bandit 1.9.4 never flagged these literals: `B105` checks plain assignments, not annotated ones
    such as `DEMO_PASSWORD: Final = "..."`. Ruff's port of the rule caught them, which is why both
    tools run.
- **Passwords hashed with a single SHA-256** (CWE-916).
  - The first version of the backend pull request stored `sha256(email + password)`. Bandit and Ruff report nothing
    on it: `B324` and `S324` flag only broken hash functions, and SHA-256 is sound for other
    purposes.
  - It was a risk because SHA-256 is fast to brute-force on a GPU. Its salt, the e-mail address,
    is public and the same on every deployment, and the hash broke when the address changed.
  - Fixed in the review: argon2id behind `IPasswordHasher` (`src/whadio/accounts/passwords.py`).
    An unknown e-mail address costs one hash, so the response time does not reveal which accounts
    exist.

## The pre-commit hook in action (bonus)

Besides the `B105` stop above, we staged a file containing a fake GitHub token and ran the hook.
It refused the commit:

```text
Detect hardcoded secrets.................................................Failed
- hook id: gitleaks
- exit code: 1

Finding:     GITHUB_TOKEN = "REDACTED
Secret:      REDACTED
RuleID:      github-pat
File:        leak_demo.py
Line:        1
WRN leaks found: 1
```

## Dependency audit (bonus)

- **uv audit**, in CI: 0 known vulnerabilities in 215 packages.
- **Dependabot:** its first two update pull requests, for the GitHub Actions and for `uv-build`,
  are merged.
- **Accepted finding.** deptry reports `torchaudio` and `torchcodec` as declared but never
  imported (`DEP002`).
  - We declare them only to pin them to torch's CPU index, because mismatched torch builds abort
    the process.
  - The exception and its reason are in `pyproject.toml`.

## Conclusions

- **One security tool is not enough.** Ruff's port of Bandit caught the demo credentials, which
  Bandit itself missed.
- **Most risks had no rule.** The forged results, the logged links, the echoed password and the
  weak password hash were found by review and by reading the system's own output. That is why
  the team charter makes review mandatory.
- **Every exception carries its reason,** so a review can check whether the reason still holds
  when the code around it changes.

## AI Usage

Drafted with Claude Code (Claude Opus 5.5) from the repository's configuration, a Bandit run on `2d2c949` and the PR #68 review; checked by Denys Zabiiaka.

The sections from "Further findings" on were drafted with Claude Code (Claude Opus 5.5), which
also ran the tools; checked by Andrii Shalaiev.
