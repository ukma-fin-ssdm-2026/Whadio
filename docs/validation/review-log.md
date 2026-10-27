# Review Log

**Owner:** Andrii

The Lab 7 reviews of our work: the peer review of the [test plan](test-plan.md) by another team,
the internal review of the same plan, and the review of AI-generated code against the course
checklist. Each review was left on its pull request; this log sums up what it found and what we
changed.

## Peer review of the test plan

- **Reviewer team:** pun-intended-team, review by Viktoriya Baran (`viktoriyabaran`).
- **Reviewed:** [#152](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/152), the test plan and the RTM, against `main` at `e8e9c1b`, on 2026-10-25.

### Checklist

| # | Criterion | Yes/No | Comment |
|:-:|---|:-:|---|
| 1 | Key requirements and critical paths are covered | No, Blocking | Sign-in is in scope but has no test case or risk |
| 2 | Acceptance criteria are clearly stated | Yes | Nit: TC-NFR-04 cannot show NFR-015's 95% |
| 3 | Negative scenarios are tested | Yes | Nit: two restricted-content paths and one preset case have no negative test |
| 4 | Tests trace to the requirements | No, Blocking | Requirements with tests at the baseline are marked "Not covered" or "Out of scope" |
| 5 | The plan is realistic and runnable in CI | Yes | |

### Strengths

1. The risks are ranked by cost, the table follows them, and gaps are stated openly. Every "exists"
   claim the reviewers checked holds.
2. Pipeline cases come in pairs: CI checks the wiring with stub models, the GPU machine checks what
   only real models decide, and a pass in one never stands in for the other.
3. Thresholds are measurable and honestly reported: TC-NFR-03 notes that three runs cannot show
   90%, and Results records the commit, configuration and measured values.

### Areas to improve

1. Trace the tests that already exist, so the RTM shows what the suite really covers.
2. Turn TC-NFR-04 into an automated test, so less of the plan depends on manual runs on one
   machine.

### Changes made

All four findings were fixed in #152 before it merged.

| Finding | Label | Change |
|---|---|---|
| Sign-in has no test case or risk | Blocking | Sign-in became risk (2). TC-ACC-01 (the service) and TC-ACC-02 (sessions and MCP keys over HTTP) cite the existing tests and trace to US-001, US-018 and NFR-012. |
| The RTM misses existing tests | Blocking | Every RTM cell maps each `Test-NN` to a plan case, or says "not covered" or "out of scope" for that case alone. Built features with tests but no case got rows: TC-WS-01, TC-SHR-01, TC-EDIT-01, TC-FLD-01, TC-CAP-01, TC-CTX-01, TC-GLO-01, TC-RET-01 and TC-ACL-03. |
| TC-NFR-04 cannot show NFR-015's 95% | Nit | TC-NFR-04 is now an automated test in CI. With processing and storage unavailable, it sends 20 requests to each of the five functions NFR-015 names and requires at least 95% of each to succeed. |
| Two content paths and a preset case lack negative tests | Nit | The recording link and the transcript revisions joined TC-ACL-02's parametrized paths, which now has no exceptions. US-006 Test-03 got TC-PRE-01: a workspace refuses a `prompt` field. |

## Internal review of the test plan

- **Reviewer:** Zlata Tsepkalo (`t-zlata`), assisted by Codex, as she disclosed.
- **Reviewed:** #152, in three rounds on 2026-10-25 and 2026-10-26; approved on 2026-10-26 after
  13 findings.

| # | Finding | Change |
|:-:|---|---|
| 1 | The RTM maps whole stories (US-007, US-012, US-013, US-015, US-018) to one or two cases | Each `Test-NN` maps to its own case, or is marked "not covered" or "out of scope" |
| 2 | TC-ACL-02 claims every content path but leaves out two | Tests added for the recording link and the transcript revisions, rather than a "partial" label |
| 3 | NFR-007 and NFR-009 are "covered" without those two paths | Covered once finding 2 was fixed; both paths use the same authorization as the others |
| 4 | NFR-010 is "covered" without transcript edits and share-request decisions | Tests added for transcript edits, speaker renames, meeting deletion, and share approvals and refusals; TC-AUD-02 lists every action it covers |
| 5 | TC-NFR-03's three runs cannot show NFR-002's 90% | TC-NFR-03 stays a smoke check of the 900 s budget and says it cannot verify NFR-002; the RTM marks NFR-002 as partial and names the 20-recording benchmark |
| 6 | The GPU instructions do not make the ASR worker use the GPU | The entry criteria require the CUDA Compose file and diarization on `cuda`, and each run records the GPU, driver and CUDA version |
| 7 | TC-NFR-04 does not measure the 95% | Same change as the peer review's TC-NFR-04 finding |
| 8 | TC-NFR-02 times the API, not the page NFR-001 names | The row says it is a proxy for QA-1's 200 ms share of the page budget; the RTM marks NFR-001 as partial |
| 9 | Results does not meet the plan's own exit criteria | Every GPU-machine case has a Results row. The CI run links on `main` are still to be added |
| 10 | The baseline does not contain [#151](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/151), which the GPU criteria need | #151 merged first and the baseline moved to `main` at `69d178d` |
| 11 | TC-ASR-01 ran only on the CPU | Results keeps the CPU row and adds a CUDA row with the GPU, driver and timings |
| 12 | NFR-009 does not trace to the share tests, and US-016 Test-02 has no test | NFR-009 traces to TC-SHR-01 too; a test shows that a signed-out visitor gets `401` and no content from a share |
| 13 | US-001 Test-03 maps to a case that never opens a meeting link | A test opens the meeting, transcript and notes without a session and gets `401` with no content; TC-ACC-02 names it |

## AI-generated code review

- **Pull request:** [#155](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/155), the processing e-mails of FR-024 (US-009). A Claude Code agent wrote the
  implementation from tests committed red beforehand; see «Бонуси», entry 3, in the
  [test plan](test-plan.md#бонуси).
- **Reviewer:** Zlata Tsepkalo (`t-zlata`), the team's AI code reviewer, on 2026-10-25, assisted by
  Codex, as she disclosed.

| # | Criterion | Yes/No | Comment |
|:-:|---|:-:|---|
| 1 | Every imported package is real and used | Yes | The implementation adds no dependency. Its standard-library, FastAPI, Pydantic, SQLAlchemy and internal imports resolve in the project, and Ruff reports no unused imports. |
| 2 | Error handling covers realistic failures, not only the happy path | Yes | The tests cover permanent failures, retry exhaustion, dead letters, unpublishable jobs, duplicate and late results, retryable failures below the limit, missing read access and notification deduplication. `PolicyMeetingReaders.can_read` deliberately converts `NOT_FOUND` to `False` and re-raises other `UseCaseError` values so unexpected failures roll back the processing transaction, but that re-raise branch has no direct test. |
| 3 | The logic matches the requirements and the test plan | Yes | The uploader receives a metadata-only `processing_finished` notice after notes are stored or a `processing_failed` notice after a final failure. The notice is reserved in the same transaction as the processing result and only when the uploader can still read the meeting, matching FR-024, US-009, TC-PROC-04 and TC-PROC-05. The per-meeting, per-recipient, per-outcome dedupe key means a future manual retry that reaches the same final outcome would not produce a second email; no current flow re-queues a finally failed meeting. |
| 4 | No dead code | Yes | `ProcessingOutcome`, both new Protocols, both adapters and `_finally_failed` are used by the production composition root. The service and adapter tests exercise both outcomes and the refusal paths. Import-linter reports all eight architecture contracts kept. |
| 5 | The author explained the key decisions when asked | Yes | The author explained the outcome-based dedupe scope, why it is safe for the current workflow, the deliberate propagation of unexpected access-policy errors, and the extraction of `_finally_failed` to keep all terminal-failure paths consistent. |

Every criterion passed, but the review still requested changes, and her notes were answered in #155:

| Note | Answer |
|---|---|
| No test sends a processing result through the production wiring to the outbox | The wiring became a function the tests can build. A worker's message now goes through the real result handling into that service, and the test checks the job, the meeting state and the outbox row together; a replayed result adds no row |
| The re-raise in `can_read` has no test | A test makes the meeting lookup fail with another error and checks that `can_read` passes it on |
| A meeting processed again would get no second e-mail, since the dedupe key has no run ID | No change: nothing processes a meeting again in the MVP, as notes regeneration is out of scope. The key should take the run's ID when regeneration lands |

## Reflection

- **Both reviews found the same kind of defect: a claim stronger than its evidence.** "Covered" sat
  on whole stories that one case touched, and two cases promised thresholds (90%, 95%) they could
  not measure. Where a test was cheap we added it; otherwise we narrowed the claim to "partial" and
  named what would verify it.
- **The AI code looked right and passed all five checklist items.** Its gap was elsewhere: every
  test used fakes, so nothing showed that the production wiring sent the notice in the processing
  transaction. Checking where generated code is called from, and not only what it does, is the
  part of the review the checklist does not prompt for.
- **Findings tied to a baseline commit and a line were quick to check.** All of the external
  review's references could be verified in minutes, and none was wrong.

## AI Usage

Drafted with Claude Code (Claude Opus 5.5) from the reviews and replies on #152 and #155, and
checked by Andrii. The reviewers disclosed their own use: Viktoriya's review was drafted with Claude
Code, and Zlata's with Codex.
