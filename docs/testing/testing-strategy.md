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

The latest recorded non-model coverage is **88%** overall. The focused modules reached 98% for
`access_policy/services.py`, 97% for `meetings/services.py`, 100% for
`access_policy/repositories.py` and 87% for `meetings/repositories.py`. The committed
[`htmlcov/`](../../htmlcov/index.html) report and [coverage report](testing.md) are the baseline.
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
| Coverage | Overall non-model line coverage must not fall below **88%**. Access Policy and Meetings service coverage must remain at least **95%**. New or changed domain behaviour must be exercised; a lower number needs a documented risk-based justification. Branch coverage will replace line-only coverage after one stable baseline run. |
| Critical requirements | NFR-007 to NFR-013 require 100% of their enumerated authorization, authenticity, integrity and audit scenarios to pass. Coverage percentage cannot substitute for these tests. |
| Regression policy | Every fixed defect receives a regression test that fails before the fix. The debugging log links the defect, fix and test. |
| Merge gate | `uv run --frozen task check`, the complete non-model suite against migrated Compose services, OpenAPI lint, dependency audit and secret scan must pass; the PR also needs approval. Model-affecting changes additionally run the relevant model tests manually or on a capable runner. |
| Release gate | Core system and acceptance journeys pass on the release candidate, with no unresolved Critical or High security finding and no unexplained coverage regression. |

## CI/CD use and ownership

The Testing Strategist owns the scope, targets, exceptions and interpretation of results. The
Integration Lead implements and maintains the jobs, caches, services and artifacts that enforce
them. Fast unit tests and static checks run on every commit; CI runs all checks plus integration
tests, audits and API lint on every push and pull request. CI should publish JUnit and coverage
artifacts and fail when the agreed coverage floors regress. System, performance and model suites
run before a release and on relevant changes; expensive scheduled runs do not weaken pull-request
gates. A failing gate is fixed, or its policy is changed transparently in a reviewed PR; checks are
never bypassed ad hoc.

## Next improvements

1. Add the two ordinary missing tests and multi-session tests for race guards.
2. Establish branch-coverage and frontend component/E2E baselines, then propose thresholds.
3. Add property-based validation tests and k6 performance scenarios.
4. Automate the Compose system journey and publish coverage/JUnit artifacts through CI.

## AI Usage

This strategy was prepared with OpenAI Codex from the requirements, threat model, quality
attributes, current tests, coverage report and CI configuration. Zlata owns the decisions, reviewed
the targets and is responsible for the final document.
