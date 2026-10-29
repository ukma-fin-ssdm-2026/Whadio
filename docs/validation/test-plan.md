# Test Plan

**Test planner:** Andrii

**Baseline:** `main` at `69d178d`, October 2026

**Builds on:** [Testing Strategy](../testing/testing-strategy.md) (levels, coverage gate, merge and release gates)

This plan states when the recording-to-notes path of Whadio counts as verified.

**Scope.** In scope: sign-in, operator-issued registration links and their completion through the API, uploading a recording, the processing pipeline from the queued job to
the stored transcript and notes, access to restricted meetings over every content path, the audit
log, exports, job monitoring, and reading results in the web app. Not tested here: features with
no API yet (self-service email registration, invitations, membership changes and password reset in US-001, US-002 and
US-020; notes regeneration, US-010; a workspace's own model provider, US-008; server load and model usage on the admin dashboard, US-019 Test-03); screens the web app
does not have yet (registration, folders, transcript edits, shares, the glossary), so those are tested through the API
and the user-action limits of NFR-005 and NFR-006 are not measured; the Chrome extension capture
(US-003, NFR-004); recognition quality scores (WER needs a reference corpus we do not have); real
models or paid services in CI.

**Exit criteria.** Every row marked CI passes in `uv run task test:cov` on `main`, with a link to
the run; coverage stays at or above the strategy's 85% line and branch; no test fails or is flaky;
every row marked GPU machine has a recorded run in [Results](#results) at a stated commit; no
defect labelled Blocking is open against a row.

**Risks, most expensive first.** (1) A restricted meeting's content reaches someone outside its
audience. (2) Someone gets in without valid credentials, or a revoked MCP key or ended session
still works. (3) A meeting is lost, processed twice or stuck in `processing` after a worker fails.
(4) An auditable change leaves no record, or a record carries meeting content. (5) Invalid input
reaches the workers. (6) Meeting lists get slow. The table follows this order, then covers the
other built features story by story, and ends with the checks that need the real models.

## Test cases

One row is one test case. Requirements are the user stories and NFRs in
[`rtm.md`](../requirements/rtm.md), with the story's `Test-NN` case where one matches. Unit rows
appear only where they guard a risk above; the strategy's coverage gate keeps the rest of the unit
suite broad.

Most pipeline cases come in pairs: CI checks the wiring with stub models (states, retries,
refusals, nothing lost), and the GPU machine checks what only the real models decide (language,
speakers, preset sections, time). A pass in one never stands in for the other.

| ID | Component / function | Level | Type | Expected result / acceptance criterion | Owner | Requirement | Runs in / status |
|---|---|---|---|---|---|---|---|
| TC-ACL-01 | Access Policy: reading a restricted meeting | Unit | Negative | A member without a grant is told the restricted meeting is missing, as if it did not exist. | Valeriia | US-015 (Test-01, Test-02), NFR-007 | CI, exists |
| TC-ACL-02 | Every path that returns meeting content | Integration | Negative | For a meeting restricted to its Owner, a member gets `404` and no content from the meeting, transcript, notes, both exports, the recording link and the transcript revisions; the meeting list, the MCP tools and other meetings' notes context omit it. Zero content on 100% of the paths (NFR-007, NFR-009). | Valeriia | US-015 (Test-02, Test-03), US-007 (Test-03), US-018 (Test-04), NFR-007, NFR-009 | CI, exists |
| TC-ACC-01 | Accounts: signing in | Integration | Negative | A wrong password and an unknown address are refused the same way and start no session; a session token is stored only as its hash. | Denys | US-001 (Test-02), NFR-012 | CI, exists |
| TC-ACC-02 | Sessions and MCP keys over HTTP | Integration | Negative | A wrong password gets `401 INVALID_CREDENTIALS`; a request without a session, with a signed-out cookie or with a revoked or expired MCP key is refused, and a signed-out visitor opening a meeting link gets `401` and none of its content; an MCP key is shown once and stored only as its hash. | Denys | US-001 (Test-02, Test-03), US-018 (Test-01, Test-03), NFR-012 | CI, exists |
| TC-ACC-03 | Accounts: operator-issued registration | Integration | Positive | The CLI issues a 24-hour link with only its token hash stored, and refuses an existing account with exit code 1 and an error on stderr. Completing a link through the API with a name, strong password and Terms acceptance atomically creates the account, personal workspace, Owner membership, default folder and browser session. Email delivery and SPA completion are pending. | Valeriia | US-001 (Test-01 completion only, Test-08), NFR-012 | CI, exists |
| TC-ACC-04 | Accounts: registration link lifecycle | Unit, Integration | Negative | Unknown, wrong-token, expired, used and replaced links, and links whose address has since acquired an account, return the same `404 LINK_INVALID`. Expiry includes the exact 24-hour boundary; a link works just before it. The scheduler deletes expired pending registrations, preserves valid ones, and continues other jobs after a cleanup failure. Repeated cleanup is harmless. Reissue replaces the previous token case-insensitively. Concurrent redemption has one winner, and failure creating the default folder rolls back the account and restores the pending registration. | Valeriia | US-001 (Test-04, Test-08), NFR-012 | CI, exists |
| TC-ACC-05 | Accounts: registration validation | Unit, Integration | Negative | A weak password or Terms acceptance other than explicit true returns `422 VALIDATION_ERROR`; the offending field is named and the link remains unconsumed. The password schema publishes and enforces the 12-128 length bounds. Accepted passwords retain surrounding spaces, including at the bounds. The registration form remains pending. | Valeriia | US-001 (Test-09), NFR-012 | CI, exists |
| TC-ACC-06 | Accounts: instance admission mode | Unit, Integration | Negative | The default is invite-only. Public `GET /instance` reports the injected mode and application API version without reloading configuration. The composition root shares its cached web settings with startup validation. Unit tests cover both admission modes with and without SMTP: only verified mode without SMTP is refused. An isolated startup test checks that the guard is wired in without connecting to external services. Hiding registration controls in the SPA is not covered yet. | Valeriia | US-001 (Test-06 backend only) | CI, exists |
| TC-ADM-01 | Admin & Monitoring: job monitoring | Integration | Negative | An administrator reads each job's state, waiting time and known failure reason, and nothing from a recording, transcript or notes; a workspace role grants no admin access, and a revoked administrator is refused at once. | Valeriia | US-019 (Test-01, Test-02, Test-04) | CI, exists |
| TC-PIPE-01 | Processing pipeline, upload to notes | Integration | Positive | Real PostgreSQL, RabbitMQ and SeaweedFS, stub ASR and notes models: a recording uploaded while no worker runs stays `queued`; once the workers start, the meeting reaches `processed` and the API returns one transcript and one set of notes. | Andrii | US-004 (Test-01), US-005 (Test-02), US-006 (Test-02), NFR-014 | CI, planned |
| TC-PIPE-02 | Processing pipeline, notes provider failure | Integration | Negative | A provider that refuses the key or the request: the meeting ends `failed` with `provider_rejected`, the transcript stays readable, no further notes job is queued. A provider unavailable on every attempt: at most 5 attempts (`MAX_ATTEMPTS`), then `failed` with `provider_unavailable`. | Andrii | US-004 (Test-03), NFR-014 | CI, planned |
| TC-NFR-01 | Processing pipeline, worker crash | Integration | Negative | The ASR worker is killed after it reports `job_started`; after a restart the meeting reaches `processed` with exactly one transcript (NFR-014: 100% of received meetings stay stored, visible and processable). | Andrii | NFR-014, US-004 | CI, planned; also on the GPU machine |
| TC-PROC-01 | Processing: repeated results | Unit | Negative | A duplicate or late result of a finished job queues nothing more and leaves the meeting unchanged. | Denys | NFR-014, US-004 | CI, exists |
| TC-PROC-02 | Processing: retry limit | Unit | Negative | A retryable failure past the attempt limit fails the meeting with its reason; the job is not published again. | Denys | US-004 (Test-03) | CI, exists |
| TC-PROC-03 | Processing: the transcription job's state table | Unit | Negative | Each of the 25 state and event pairs in [Бонуси](#бонуси) leaves the job in the state the table names; an event the state does not accept changes nothing. | Andrii | US-004 (Test-03) | CI, exists |
| TC-PROC-04 | Processing: notices of a meeting's outcome | Unit | Positive | The uploader is notified once when the meeting is processed and once when its processing finally fails (a permanent failure, a retryable one at the attempt limit, a dead letter, a job that cannot be published); nobody is notified for a retry below the limit, a transcript still waiting for notes, a late result, or an uploader who can no longer read the meeting. | Andrii | US-009 (Test-01, Test-03) | CI, exists |
| TC-PROC-05 | Processing notices in the outbox | Integration | Negative | A notice is reserved for its recipient as `processing_finished` or `processing_failed` with only the meeting's ID and name, and a repeated outcome is reserved once; the readers check follows the access policy, so a member left out of a restricted meeting and an outsider are refused, and passes on any failure but a missing meeting. A worker's result, handled through the production composition, commits the job, the meeting state and the notice together; a replay reserves nothing more. | Andrii | US-009 (Test-02), NFR-007 | CI, exists |
| TC-MTG-02 | Meetings: accepting an upload | Integration | Positive | A supported file creates one `queued` meeting, a privately stored recording and one transcription job in the outbox; nothing is published inside the request. | Valeriia | US-004 (Test-01), NFR-014 | CI, exists |
| TC-NFR-04 | Core features during a processing outage | Integration | Positive | The API runs with no processing integration and no storage, which is how it sees a stopped worker, broker or LLM runtime. 20 requests go to each function NFR-015 names: sign-in, the workspace list, the meeting list, a processed meeting's transcript, and the sharing settings (its access and its shares). At least 95% of each function's requests succeed; any response but `2xx` counts as a failure. Recovery after the restart is TC-PIPE-01 and TC-NFR-01. | Andrii | NFR-015 | CI, exists |
| TC-AUD-01 | Audit: a change and its record | Unit | Positive | Renaming a meeting writes one audit event with the actor, the action and the meeting. | Denys | US-013, NFR-010 | CI, exists |
| TC-AUD-02 | Audit: every NFR-010 change the API offers | Integration | Positive | Meeting creation, renames, moves, deletions and evictions, transcript edits and speaker renames, notes regeneration, restrictions and grants, shares, share-request decisions, workspace deletion and MCP key changes each write exactly one record (actor, action type, target, time) in the same transaction, which a failed write rolls back; `details` holds no transcript, notes or recording content. Membership changes and provider configuration have no API yet. | Denys | NFR-010 | CI, exists |
| TC-AUD-03 | Audit: history cannot change | Integration | Negative | The application's database role cannot delete, update or truncate audit events, and an event survives its workspace's deletion. | Denys | NFR-010 | CI, exists |
| TC-MTG-01 | Meetings: upload validation | Unit | Negative | Bytes that do not decode as audio are refused with `415`, and no meeting is created. | Valeriia | US-004 (Test-02) | CI, exists |
| TC-NFR-02 | Meeting and workspace lists under load | System | Positive | k6, 50 virtual users for 30 s per list endpoint, one uvicorn worker: p95 at most 200 ms and no failed request, the API's share of NFR-001's 2-second page budget (QA-1). It does not time a page in the browser, so NFR-001 is covered only in part. | Zlata | NFR-001, US-013 | Manual, `tests/performance/test_lists.js` with k6 from its Docker image |
| TC-WS-01 | Accounts: creating and deleting a workspace | Integration | Positive | A new workspace has its creator as Owner and a default folder; a Member cannot delete a workspace, and nobody can delete a personal one. | Denys | US-002 (Test-01, Test-04) | CI, exists |
| TC-ACL-03 | Access Policy: who may restrict | Unit | Negative | A Member cannot restrict a meeting or change its access list, and access cannot be granted to someone outside the workspace. | Valeriia | US-015 (Test-04) | CI, exists |
| TC-SHR-01 | Access Policy: external shares | Integration | Negative | A share only reads: no export, recording, MCP or edit. It binds to the one approved account, the creator gets the access request, and a declined or revoked share reads nothing, nor does a signed-out visitor; a redacted share names the speakers Speaker 1, Speaker 2. | Valeriia | US-016 (Test-01 to Test-06), NFR-008, NFR-009 | CI, exists |
| TC-EDIT-01 | Meetings: transcript edits | Integration | Positive | Editing text or a speaker name makes a new revision marked edited; the original and the earlier revisions stay readable and cannot be relabelled; an edit of a stale revision is refused. | Valeriia | US-005 (Test-03), US-011 (Test-03), NFR-011 | CI, exists |
| TC-EXP-01 | Export: transcript and notes files | Unit | Positive | The current transcript exports with its corrections and says it was edited, the original never does; Markdown can leave out timestamps; a notes export exists only once notes do; every file carries the sharing notice and the Whadio attribution. | Valeriia | US-017 (Test-01 to Test-05), US-011 (Test-04), NFR-011 | CI, exists |
| TC-FLD-01 | Meetings: folders | Integration | Positive | Deleting a folder moves its meetings, with their recording, transcript, notes and grants, to the default folder; a meeting cannot move to another workspace's folder; a Member cannot delete someone else's meeting. | Valeriia | US-014 (Test-02 to Test-04) | CI, exists |
| TC-CTX-01 | Notes context from the folder | Integration | Positive | A notes job carries the folder's other processed meetings that are not restricted, the notes record the meetings they used, and a meeting alone in its folder still gets notes. | Valeriia | US-007 (Test-01 to Test-04) | CI, exists |
| TC-PRE-01 | Notes presets: the prompt stays private | Unit | Negative | Creating or updating a workspace refuses a `prompt` field, and the import-linter contract "Runtimes are independent of each other" keeps the API from importing the notes worker, where the prompts live. | Andrii | US-006 (Test-03) | CI, exists |
| TC-GLO-01 | Meetings: workspace glossary | Integration | Positive | Terms are kept per workspace, a term differing only in case is refused, and the next transcription job hands the glossary to the recognizer. | Valeriia | US-012 (Test-01 to Test-03) | CI, exists |
| TC-RET-01 | Retention: deleting a recording | Integration | Positive | Once retention deletes a recording, its transcript and notes stay readable. | Valeriia | US-011 (Test-02) | CI, exists |
| TC-CAP-01 | Meetings: hosted capacity | Integration | Positive | A meeting queued past the hosted limit evicts the earliest meeting across the uploader's owned workspaces, audited and attributed to the uploader; a failed upload rolls the eviction back; an open capture does not count. | Valeriia | NFR-003 | CI, exists |
| TC-PIPE-03 | Whole stack with real models | System | Positive | A 10-minute Ukrainian recording with several speakers, uploaded in the web app, reaches `processed`; the transcript is in `uk` with at least two speakers (Speaker 1, Speaker 2…); the notes have the workspace's default preset sections and name the configured model; the list, transcript, notes and playback show in the web app. Once with Claude, once with Ollama. | Andrii | US-004 (Test-01), US-005 (Test-02), US-006 (Test-01, Test-02), US-013 (Test-02) | GPU machine, manual |
| TC-ASR-01 | ASR worker: real models | Integration | Positive | The `models` tests pass: Parakeet and Whisper recognize their reference clips, and the diarizing slot tells two speakers apart. | Andrii | US-005 (Test-02) | GPU machine, `pytest -m models` |
| TC-ASR-02 | ASR worker: glossary with Whisper | System | Positive | A glossary term Parakeet misspelled appears in its preferred form in a Whisper transcript of the same clip. | Andrii | US-012 (Test-02) | GPU machine, manual |
| TC-NOTES-01 | Notes worker: real Ollama limits | Integration | Negative | A prompt longer than the context window and an answer that runs out of it fail as `transcript_too_long`; an answer cut by the answer limit fails as `invalid_output`; a short answer succeeds. | Andrii | US-006 | GPU machine, `pytest -m slow` with Ollama |
| TC-NFR-03 | Transcription time | System | Positive | A 60-minute public Ukrainian recording, alone in the queue, has its transcript ready within 900 s of being queued in each of three runs; one miss fails. The three runs are a smoke check of NFR-002's budget: they cannot show its 90%, which the 20-recording benchmark in the [traceability matrix](../architecture/traceability-matrix.md) verifies. | Andrii | NFR-002 | GPU machine, manual |
| TC-NFR-05 | ASR pipeline: transcription time | Integration | Positive | The ASR pipeline (download, decoding, diarization, recognition) transcribes a 59–61 minute recording within 900 s, with diarization on CUDA, in each of three runs; one miss fails. The three runs are a smoke check: like TC-NFR-03's, they cannot show NFR-002's 90%. Queueing and the upload are left out, which TC-NFR-03 times. | Andrii | NFR-002 | GPU machine, `pytest -m models` |

## Entry criteria

- The case's feature is on `main`, and its requirement has an ID in `rtm.md`.
- The Compose services run with migrations applied, and `WHADIO_TEST_DATABASE_URL` is set.
- GPU machine runs: a team member's machine with a 12 GB NVIDIA GPU, both Compose profiles, and
  `COMPOSE_FILE=compose.yaml:compose.cuda.yaml` with `WHADIO_ASR__DIARIZATION__DEVICE=cuda`, which
  put diarization on the GPU; recognition stays on the CPU. Models downloaded, nothing else
  transcribing, and the commit, GPU, driver, CUDA version, models and configuration noted before
  the run.
- Recordings are never committed. A transcript goes to Anthropic only if everyone recorded agreed;
  otherwise the run uses the public recording.

## Manual and GPU runs

Start the full stack as in the [README](../../README.md), with `uv run task llm:up` for the Ollama
runs, and record each run in [Results](#results).

- **TC-PIPE-03.** Upload a 10-minute clip of a team meeting in the web app and wait for
  `processed`. Check the speakers, language and preset sections, and play the recording. Then set
  `WHADIO_NOTES__LLM__PROVIDER=ollama` and a model, recreate the notes worker, and repeat; note the
  notes time and peak GPU memory.
- **TC-ASR-02.** Add a term Parakeet got wrong in TC-PIPE-03 to the glossary, set
  `WHADIO_ASR__RECOGNIZER=whisper`, recreate the ASR worker, and transcribe a 3-minute clip that
  contains it.
- **TC-NFR-01, system run.** Kill the `asr-worker` container while a meeting is `processing`,
  check that it is still listed with its state, start the worker, and wait for `processed`.
- **TC-NFR-03.** Upload the 60-minute recording into an empty queue and time `queued` to transcript
  ready; three runs, one at a time. Also note how its notes end: written from parts, or a clean
  `transcript_too_long` failure.

## Results

| Case | Date | Commit | Configuration | Result | Measured | Defects |
|---|---|---|---|---|---|---|
| Every row marked CI, exists | 2026-10-27 | `main` at `07c55e4` | GitHub Actions, [CI/CD run 40464159113](https://github.com/ukma-fin-ssdm-2026/Whadio/actions/runs/40464159113): `uv run task test:cov` with PostgreSQL, RabbitMQ and SeaweedFS from `task infra:up`, without the `models` tests | Pass | 1386 passed, 4 skipped; line and branch coverage 91.09% against the 85% gate | None. TC-PIPE-01, TC-PIPE-02 and TC-NFR-01 are marked CI, planned: they have no test yet, so no run |
| TC-ASR-01, CPU | 2026-10-25 | `0a7db9f` | GPU machine (i5-10400F, RTX 4070 12 GB, WSL2), all models on the CPU | Pass | — | None |
| TC-ASR-01, CUDA | 2026-10-26 | #151 at `813db7e`, which contains `main` at `fd016a4` | GPU machine (i5-10400F, RTX 4070 12 GB, WSL2), driver 595.97 (CUDA 13.2), `cuda` extra with torch 2.14.1+cu130; Parakeet TDT 0.6B v3 int8 and Whisper large-v2 int8 on the CPU, pyannote community-1 on the GPU in the `[cuda]` case | Pass, 5 of 5 | The `[cuda]` speaker case took 8.4 s against 18.0 s for `[cpu]`; GPU memory peaked at 848 MiB | None |
| TC-NOTES-01 | 2026-10-25 | `0a7db9f` | Ollama in Compose, `gemma4:12b-it-qat` | Pass, 4 of 4 | 138 s, mostly model loading | None |
| TC-NFR-02 | 2026-10-26 | `35fac12` | Windows, k6 0.54.0 in Docker, one uvicorn worker, 50 virtual users for 30 s per endpoint | Fail | Workspace list: p95 460.56 ms, 28 of 1227 requests failed (2.28%); meeting list: p95 637.83 ms, 29 of 1191 failed (2.43%) | [#162](https://github.com/ukma-fin-ssdm-2026/Whadio/issues/162): QA-1's 200 ms API budget exceeded, and requests failed. It does not show NFR-001 failing, which TC-NFR-02 does not measure |
| TC-PIPE-03 | 2026-10-25 | `0a7db9f` | GPU machine, ASR on the CPU; a 10-minute team meeting; Claude, then `gemma4:12b-it-qat` in Compose | Pass, both | Transcript in 420 s and 443 s; notes in 13 s (Claude) and 21 s (gemma4, 8.5 GB of GPU memory at a 32k context) | None |
| TC-PIPE-03, model comparison | 2026-10-25, 2026-10-26 | #151 at `a8eb270`; its later commits add only a test, CI and documentation | GPU machine, diarization on the GPU; a 19.5-minute team meeting with 4 speakers, `summary` and `detailed` presets; Claude, `gemma4:12b-it-qat`, `gemma4:12b-it-q4_K_M`, `qwen3:8b` | Pass, 8 of 8 valid at the first try, in Ukrainian with the preset's sections | Notes in s (summary / detailed): Claude 8 / 17, qat 18 / 18, q4_K_M 33 / 12, qwen3 33 / 18; peak GPU memory with the ASR worker 9.7, 10.3 and 10.6 GB | None. Diarization found 3 of the 4 speakers; Claude invented nothing, the local models added tasks or dates nobody said |
| TC-NFR-01, system run | 2026-10-25 | #151 at `a8eb270` | GPU machine, Compose; a 19.5-minute team meeting, `gemma4:12b-it-qat` | Pass | ASR worker killed 60 s into the job; after the restart the job was delivered again: 1 job, 1 transcript, 1 set of notes | None |
| TC-NFR-04, system run | 2026-10-25 | #151 at `a8eb270` | GPU machine, Compose with `asr-worker`, `notes-worker` and `llm-runtime` stopped | Pass | Sign-out and sign-in, both lists, transcript, notes, access, shares, the recording link and the web app all answered `200`; an upload stayed `queued` and was processed 50 s after the restart | None |
| TC-ASR-02 | 2026-10-26 | #151 at `39b46b3` | Whisper large-v2 int8 on the CPU; a 3-minute team clip | Pass | Parakeet and Whisper without the glossary misspelled "Ollama"; with the term in the glossary Whisper spelled it right; Whisper took 88–110 s for 180 s | None |
| TC-NFR-03 | 2026-10-25 | #151 at `a8eb270`; the first run on an earlier revision of #151 | GPU machine (i5-10400F, RTX 4070 12 GB, WSL2), Compose with `compose.cuda.yaml`: pyannote community-1 on the GPU, Parakeet TDT 0.6B v3 int8 on the CPU, 1 slot | Pass, 3 of 3 | Queued to transcript ready in 434 s, 425 s and 437 s, against 900 s. The first run spent 67 s in pyannote and 351 s in Parakeet. Notes came from 1 part at `num_ctx` 32768 and from 4 parts at 20480; at 17800 a team meeting failed cleanly as `transcript_too_long` at the reduce step, with its transcript kept | Without a GPU it misses: transcription takes 0.70–0.74 of the recording's length (#150) |
| TC-NFR-05 | 2026-10-27 | #153 at `37afed5`, whose tree equals `main` at `6bc9a84` | GPU machine (i5-10400F, RTX 4070 12 GB, WSL2), driver 595.97 (CUDA 13.2), `cuda` extra with torch 2.14.1+cu130, `WHADIO_ASR__DIARIZATION__DEVICE=cuda`: pyannote community-1 on the GPU, Parakeet TDT 0.6B v3 int8 on the CPU; the 60.1-minute recording behind TC-NFR-03 | Pass, 3 of 3 | 390 s, 388 s and 382 s against 900 s, with the models loaded beforehand (about 22 s, not timed); GPU memory peaked at 1.0 GiB | None |

## AI Usage

Drafted with Claude Code (Claude Opus 5.5) from Zlata's initial draft (OpenAI Codex) and the GPU
machine runs, and checked against the code at `69d178d`. The team reviews it before merging.

The registration scope and TC-ACC-03 through TC-ACC-06 were drafted by Valeriia with OpenAI Codex.

## Бонуси

### 2. State-transition table

`processing/test_services.py::test_transcription_job_follows_the_state_table` applies state
transition testing to the transcription job. Each cell below is one parametrized case with the ID
shown. The states and events come from `ProcessingService.handle` and `dead_lettered`, with
`MAX_ATTEMPTS` = 5. A cell where the state stays the same is a transition the job refuses: the
test checks that it leaves the job's status, attempts, publication and failure reason, the
meeting's state, its transcript and the other jobs all as they were. Every other cell must
change exactly what it names, such as ST-08 queueing the job to be published again.

| State \ event | Started | Transcript ready | Retryable failure | Permanent failure | Dead-lettered |
|---|---|---|---|---|---|
| Queued | ST-01: running | ST-02: succeeded | ST-03: queued | ST-04: queued | ST-05: failed |
| Running, attempt 1 of 5 | ST-06: running | ST-07: succeeded | ST-08: queued, retried | ST-09: failed | ST-10: failed |
| Running, attempt 5 of 5 | ST-11: running | ST-12: succeeded | ST-13: failed | ST-14: failed | ST-15: failed |
| Succeeded | ST-16: succeeded | ST-17: succeeded | ST-18: succeeded | ST-19: succeeded | ST-20: succeeded |
| Failed | ST-21: failed | ST-22: failed | ST-23: failed | ST-24: failed | ST-25: failed |

Run it with `uv run pytest src/whadio/processing/test_services.py -k state_table -v`.

### 3. Tests as a specification for an agent

The processing e-mails of FR-024 (US-009, TC-PROC-04 and TC-PROC-05) were specified as tests
before any code sent them, and an AI agent then wrote the code from those tests alone.

1. `8ed4d71`, `test(#87): [RED] specify the processing notices`. Eleven service tests and six
   adapter cases, written by hand. The 13 that describe missing behaviour are strict xfails, which
   pass the commit hook without bypassing it; the 4 refusals already held and pass. It also adds
   the two Protocols and adapters that raise `NotImplementedError`, so the tests can run.
2. `761a0c2`, `feat(#87): send processing notices from the outbox`. The implementation, with the
   xfail marks removed and no test changed.

**Використання ШІ.** A Claude Code agent (Claude Opus 5.5) wrote `761a0c2`, given only the red
tests and `AGENTS.md`. The tests were green on its first run, with every static check passing; no
code was fixed by hand. It also merged the three final-failure paths into `_finally_failed`, and
reported three points: a second failure of a re-queued meeting would not be mailed (no path
re-queues a failed meeting today), `database.md` still called the notices unfinished (now
updated), and one untested re-raise in `PolicyMeetingReaders.can_read` (tested since the review). Its review against the AI-code
checklist goes into `review-log.md`.

### 4. Executable non-functional test

`workers/asr/test_slot.py::test_hour_recording_is_transcribed_within_the_nfr_002_budget` is
TC-NFR-05, a test of NFR-002's threshold. The ASR pipeline must transcribe a 59–61 minute
recording within 900 s, in each of three runs, with diarization on CUDA. The models load before the timed part, as they do
once per worker in production.

- **Threshold:** 900 s, NFR-002's 15 minutes for a recording of up to one hour.
- **Measured:** the time of each run, in [Results](#results), row TC-NFR-05.
- **Run** on the GPU machine, with the `cuda` extra installed and diarization on the GPU:

  ```bash
  WHADIO_TEST_HOUR_RECORDING=<a 59-61 minute recording> WHADIO_ASR__DIARIZATION__DEVICE=cuda \
    uv run --extra asr --extra cuda pytest -m models src/whadio/workers/asr/test_slot.py -k nfr_002 \
    --durations=3
  ```

  `--durations` prints each run's time. Without the recording the test skips; a recording outside
  59–61 minutes, or diarization set to anything but `cuda`, fails it before the timing starts.
  Three runs cannot show NFR-002's 90%; the 20-recording benchmark in the traceability matrix
  does.
