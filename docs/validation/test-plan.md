# Test Plan

**Owner:** Test Planner · **Based on:** [testing strategy](../testing/testing-strategy.md) (Lab 6), [RTM](../requirements/rtm.md), [requirements](../requirements/requirements.md)
**Status:** draft for cross-team review (Lab 7)

## 1. Scope

**Tested**

- Accounts, sessions and MCP keys (`accounts`, `api/accounts`).
- Access policy: workspace roles, restricted meetings, shares (`access_policy`).
- Meetings, folders and uploads (`meetings`, `api/meetings`, `api/capture`).
- Processing pipeline: queueing, retries, results (`processing`).
- Audit records and the confidentiality, integrity and recoverability NFRs.

**Deliberately not tested in routine runs**

- ASR and LLM model quality (`workers/*`). Needs weights and a GPU; evaluated separately with WER and speaker-attribution error, per the strategy.
- Third-party services (SMTP provider, Claude/Ollama). Replaced by test doubles ([test-doubles.md](../testing/test-doubles.md)).
- Visual styling of the SPA. Only the logic in `frontend/src` is unit-tested.

## 2. Exit criteria

Testing is complete for a release when all of the following hold:

1. All tests in this plan pass in CI (`uv run --frozen task check`, integration suite against Compose services, frontend tests).
2. Non-model line-and-branch coverage is at least **85%** (target from the Lab 6 strategy; baseline 88%).
3. 100% of the authorization, authenticity, integrity and audit scenarios for NFR-007 to NFR-013 pass.
4. No open Critical or High defect.
5. Every requirement in `rtm.md` has at least one test ID, and every test below has a requirement ID.

## 3. Risks

| Risk | Likelihood | Cost | Where tests concentrate |
|---|---|---|---|
| Content disclosed to an unauthorized identity (restricted meeting, share, MCP, export) | Medium: many access paths | Very high | TC-01 to TC-04, TC-13 |
| Account takeover through registration or reset links | Medium | High | TC-05, TC-06 |
| Meeting lost or stuck when a worker dies mid-job | Medium | High | TC-09, TC-10, TC-15 |
| Irreversible deletion or capacity eviction removes the wrong meeting | Low | High | TC-11, TC-12 |
| Edited transcript shown or exported as the original | Low | Medium | TC-14 |
| Slow lists or processing miss NFR thresholds | Medium | Medium | TC-16, TC-17 |

## 4. Test cases

Levels: Unit / Integration / System / Acceptance. Type: **+** positive, **−** negative. Owners: Andrii, Denys, Valeriia, Zlata. Existing tests are named; "new" means it is to be written this week.

| № | Component / function | Level | Type | Expected result / acceptance criterion | Owner | Requirement |
|---|---|---|---|---|---|---|
| TC-01 | Access policy: restricted meeting | Unit | − | A member without a grant gets "not found" for a restricted meeting (`access_policy/test_services_unit.py::test_restricted_meeting_is_missing_for_a_member_without_a_grant`) | Zlata | US-015 / NFR-007, NFR-009 |
| TC-02 | Access policy: restricted meeting via REST, share and MCP | Integration | − | Authorization matrix returns zero content bytes to every unauthorized identity on every path (new matrix test over real PostgreSQL) | Denys | US-015, US-018 / NFR-009 |
| TC-03 | Access policy: share | Unit | + | Approving an access request binds the share to the requester (`test_approving_a_request_binds_the_share_to_the_requester`) | Zlata | US-016 / NFR-008 |
| TC-04 | Access policy: share | Integration | − | A second account opening a bound share link receives no content; a revoked share is refused; no export route is reachable (new API test) | Denys | US-016 / NFR-008 |
| TC-05 | Accounts: registration link | Integration | − | A used or expired link creates no account; an existing address gets the same response as a new one (new API test with mail catcher and mocked clock) | Andrii | US-001 / NFR-018 |
| TC-06 | Accounts: password reset | Integration | + | Setting a new password ends every earlier session and extension token (new API test) | Andrii | US-020 / NFR-012 |
| TC-07 | Accounts: MCP keys | Unit | + | The key is stored only as a hash and is shown once (`accounts/test_services_unit.py::test_created_mcp_key_is_stored_only_as_a_hash`) | Andrii | US-018 / NFR-012 |
| TC-08 | Accounts: MCP keys | Integration | − | A revoked or expired key is rejected by an MCP tool call (`api/accounts/test_routes_mcp_keys.py`, extend with revoked case) | Andrii | US-018 / NFR-012 |
| TC-09 | Processing: retry | Unit | − | A retryable failure republishes the job; past the attempt limit the meeting is marked failed with its cause (`processing/test_services.py::test_retryable_failure_past_the_attempt_limit_fails_the_meeting`) | Valeriia | US-004 / NFR-014 |
| TC-10 | Processing: worker restart | System | + | Stopping the transcription worker during a job leaves the meeting stored and visible; after restart it finishes (Compose scenario) | Valeriia | US-004 / NFR-014, NFR-015 |
| TC-11 | Meetings: delete and permissions | Unit | − | A member cannot delete someone else's meeting (`meetings/test_services_unit.py::test_member_cannot_delete_someone_elses_meeting`) | Zlata | US-014 / NFR-010 |
| TC-12 | Meetings: capacity eviction | Integration | + | The 1001st queued meeting evicts the earliest-created one, writes an audit record and notifies users (`api/test_eviction_integration.py`) | Denys | US-003 / NFR-003, NFR-010 |
| TC-13 | Capture: upload | Integration | − | A wrong file type is rejected and no meeting is created (`api/meetings/test_upload_limits.py`, `api/capture/test_routes.py`) | Valeriia | US-004 / NFR-014 |
| TC-14 | Transcript editing and export | Integration | + | An edited transcript is marked "edited" in view, share and export; the original is reachable in at most 2 actions (new API test) | Zlata | US-011, US-017 / NFR-006, NFR-011 |
| TC-15 | Audit | Unit | + | Each listed action writes an audit record with actor, action, target and timestamp and no content (`test_renaming_a_meeting_is_audited`, extend to the full list) | Andrii | US-002 / NFR-010 |
| TC-16 | Meeting list API (**NFR**) | System | + | k6, 50 concurrent requests for 30 s: p95 ≤ 200 ms for the list endpoint (QA-1), and page load < 2 s for ≥ 90% of requests | Denys | US-013 / NFR-001 |
| TC-17 | Transcription pipeline (**NFR**) | System | + | A recording up to 1 h gets a transcript within 15 min in ≥ 90% of runs; measured on a capable runner before release | Valeriia | US-004 / NFR-002 |
| TC-18 | Frontend: `formatDuration` | Unit | + | Long durations are formatted as hours and minutes (`frontend/src/format-duration.test.js`) | Denys | US-013 / NFR-001 |

Coverage check: 8 components with at least two levels each (access policy, accounts, processing, meetings, capture, API, audit, frontend), 2 NFR cases (TC-16, TC-17), every row has an owner and a requirement ID.

## 5. Traceability

Test IDs are added to the "Тестові випадки" column of [rtm.md](../requirements/rtm.md) as `TC-xx`. A test with no requirement ID is either redundant or a missing requirement.

## 6. AI Usage

Drafted with Claude Code (Claude Sonnet 5.5) from the testing strategy, RTM, requirements and the existing test files; the team reviews the owners, thresholds and the "new" tests before the cross-team review.
