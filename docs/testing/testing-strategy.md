# Testing Strategy

**Owner:** Testing Strategist (Zlata)  
**Baseline:** `main` at `3a823a1`, measured in October 2026  
**Review cadence:** after a requirement or architecture change, and before every lab release

## Purpose and quality goals

Testing gives evidence that Whadio keeps private meeting content confidential, preserves data and
produces useful transcripts and notes. Effort is risk-based: authorization, authentication,
irreversible deletion, auditability and processing recovery take priority over presentation-only
behaviour. Tests should detect a regression close to the layer that introduced it and remain fast
and deterministic enough to run continuously.

The latest recorded non-model line and branch coverage is **92.42%** overall, from successful
[CI run 41335159391](https://github.com/ukma-fin-ssdm-2026/Whadio/actions/runs/41335159391).
The committed [`htmlcov/`](../../htmlcov/index.html) report and [coverage report](testing.md) are
the current baseline.
The remaining lines are mainly defensive re-raises and concurrency guards that require genuine
multi-transaction tests; two ordinary gaps remain: successful glossary rename and the happy path
of `processing_snapshot`. Model tests are excluded from routine coverage because they require
downloaded weights and GPU-capable infrastructure, not because their behaviour is unimportant.

## Test scope

| Level | What it proves | Required approach |
|---|---|---|
| Unit | Domain decisions, validation, state transitions and refusals | Test services beside their source with in-memory fakes; use Arrange-Act-Assert, one logical assertion and parametrised boundary cases. New domain behaviour needs a happy path, relevant boundaries and every authorization refusal. |
| Integration | SQL queries, constraints, transactions, API contracts, broker and storage adapters | Use the rollback-isolated PostgreSQL fixture and real module adapters. Verify ownership, cursor paging, idempotency, rollback and audit writes. Replace only external paid or non-deterministic services. |
| System | The deployed components work together | In Docker Compose, cover sign-in, upload, storage, queueing, transcription, notes generation and reading results in the SPA. Also stop and restart each worker during a job to verify NFR-014 and NFR-015. |
| Acceptance | User stories and NFRs are demonstrably satisfied | Map each acceptance criterion to an automated test or a documented manual scenario. Releases require the core recording-to-notes journey plus the authorization matrix for workspace, restricted, shared and MCP access. |

Security tests must prove **zero content disclosure** to unauthorized identities across REST,
recording, export, share and MCP paths (NFR-007 to NFR-009). Authentication tests cover wrong
passwords, missing and ended sessions, and expired or revoked keys. Audit tests cover every action
listed by NFR-010 and assert that records contain identifiers and metadata, never meeting content.
Property-based testing is planned first for display names, folder names, glossary terms, Unicode
and cursor round-trips. Performance tests use the existing QA-1 target: k6 at 50 concurrent
requests for 30 seconds, with p95 API latency at or below 200 ms; processing tests measure NFR-002
separately on one-hour recordings. Model quality is evaluated on a fixed Ukrainian/English
code-switching corpus using WER and speaker-attribution error, with corpus and model versions
recorded alongside results.

## Metrics and quality gates

| Metric or gate | Policy |
|---|---|
| Test result | Zero failed or flaky tests. A skip must name the unavailable dependency or environment. |
| Coverage | Overall non-model coverage, measured as one combined line-and-branch result, must not fall below **85%**. New or changed domain behaviour must be exercised; a lower result needs a documented risk-based justification. |
| Critical requirements | NFR-007 to NFR-013 require 100% of their enumerated authorization, authenticity, integrity and audit scenarios to pass. Coverage percentage cannot substitute for these tests. |
| Regression policy | Every fixed defect receives a regression test that fails before the fix. The debugging log links the defect, fix and test. |
| Merge gate | The `CI passed` check must pass: `uv run --frozen task check`, including OpenAPI lint and the secret scan, the complete non-model suite against migrated Compose services, the frontend's tests and build, and the worker image. The dependency audit warns but does not block. The PR also needs approval. Model-affecting changes additionally run the relevant model tests manually or on a capable runner. |
| Release gate | Core system and acceptance journeys pass on the release candidate, with no unresolved Critical or High security finding and no unexplained coverage regression. |

## CI/CD use and ownership

The Testing Strategist owns the scope, targets, exceptions and interpretation of results. The
Integration Lead implements and maintains the jobs, caches, services and artifacts that enforce
them. Cheap static checks run on every commit and fast unit tests on every push; CI runs all checks
plus integration tests, audits and API lint on every pull request and on `main`. CI should publish
JUnit and coverage artifacts and fail when the agreed coverage floors regress. System, performance
and model suites run before a release and on relevant changes; expensive scheduled runs do not
weaken pull-request gates. A failing gate is fixed, or its policy is changed transparently in a reviewed PR; checks are
never bypassed ad hoc.

## AI Usage

This strategy was prepared with OpenAI Codex from the requirements, threat model, quality
attributes, current tests, coverage report and CI configuration. Zlata owns the decisions, reviewed
the targets and is responsible for the final document.

## Бонуси

The evidence for the three Lab 6 bonuses. Andrii's contribution video explains each of them.

### 1. Mutation testing

- **What:** [mutmut](https://mutmut.readthedocs.io/) 3.8.0 mutates the notes prompt builder,
  `src/whadio/workers/notes/prompt.py`, and runs the notes worker's tests against each mutant.
  The scope is `[tool.mutmut]` in `pyproject.toml`; `uv run task mutation` runs it and lists the
  survivors. It stays out of CI: a full run is cheap here, but its result needs a person to judge
  which survivors matter.
- **How it works:** each mutant is a copy of the module with one small change, such as `<=` turned
  into `<` or a constant shifted by one. A test that fails kills the mutant; a mutant that survives
  is a behaviour no test checks, even when the line is covered.
- **Score:** 133 of 158 mutants killed (**84.2%**) before, 152 of 158 (**96.2%**) after the new
  tests. Of the 6 left, 4 are equivalent (`quote=None` and `quote=False` behave the same in
  `html.escape`; the starting speaker is reassigned before it is ever compared) and 2 only change
  the case of the task sentence for the LLM, which no code reads.
- **A survivor:** the hours of the transcript clock, `x__clock__mutmut_4`. The line was covered,
  since `3725` renders as `01:02:05`, but `3725 // 3601` is also 1:

  ```diff
   def _clock(seconds: float) -> str:
       whole = int(seconds)
  -    return f"{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}"
  +    return f"{whole // 3601:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}"
  ```

- **The test that kills it:**
  `test_rendered_transcript_clock_turns_over_at_each_minute_and_hour` checks the clock at 59, 60 and
  61 seconds and at 3599, 3600 and 3601 seconds. With the mutant, `bva-on-an-hour` renders
  `[00:00:00]` instead of `[01:00:00]`.

### 2. Property-based tests

[Hypothesis](https://hypothesis.readthedocs.io/) generates the inputs. The `ci` profile is
derandomised, so CI runs are repeatable; the `dev` profile explores new inputs on every local run
(root `conftest.py`).

| Property | Test | Why it holds for any input |
|---|---|---|
| A page's next cursor decodes to its last item | `api/core/test_pagination.py`, `test_next_cursor_decodes_to_the_last_item_of_the_page` | The cursor only encodes the sort key and the item ID; if encoding lost anything, a client would skip or repeat items while paging. |
| Accepted display text is stripped, has no control character, has a visible character, and validating it again returns it unchanged | `api/core/test_schemas.py`, five `test_*display_text*` properties | Validation either refuses a value or returns one in its normal form, whatever the Unicode it receives. |
| A built notes prompt is either refused as too long or fits the token budget | `workers/notes/test_prompt.py`, `test_built_prompt_is_refused_or_fits_the_budget` | The budget is a hard limit of the model's context window, so no request may produce a prompt over it. |

The last property found a real bug. Shrunk to 2 one-character segments, 4 context meetings and one
glossary entry, a prompt used 2,579 tokens against a budget of 2,567: the 6 `\n\n` separators
between the parts were never counted. The fix and its exact-boundary regression tests are in
[#112](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/112).

### 3. Coverage gate in CI

- **Threshold:** **85%** of lines and branches combined, set once as `fail_under` in
  `[tool.coverage.report]` in `pyproject.toml`. `uv run task test:cov` enforces it in CI on every
  pull request and on `main`.
- **Why 85%:** it was the measured total (85.6%) when the gate was introduced, after turning on
  greenlet tracing so that SQLAlchemy's async code counts as run. A gate must pass on the day it is
  introduced; 85% stops coverage from slipping below what the suite already proves, and can be
  raised while coverage remains above the 92.42% recorded above.
- **CI:** the job summary shows the coverage table and the failed tests; the JUnit and HTML reports
  are uploaded as an artifact.
- **A green run:** [run 39311660739](https://github.com/ukma-fin-ssdm-2026/Whadio/actions/runs/39311660739)
  on the course's runners, for pull request
  [#117](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/117): 1090 passed, total coverage
  **89.47%**, "Required test coverage of 85.0% reached".

This section was drafted with Claude Code (Claude Opus 5.5) from the pull requests and the mutmut
and CI results; Andrii checked it against them.
