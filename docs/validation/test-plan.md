# Test Plan

**Test planner:** Andrii

**Baseline:** `main` at `fb5cbc6`, October 2026

**Builds on:** [Testing Strategy](../testing/testing-strategy.md) (levels, coverage gate, merge and release gates)

This plan states when the recording-to-notes path of Whadio counts as verified.

**Scope.** In scope: sign-in, uploading a recording, the processing pipeline from the queued job to
the stored transcript and notes, access to restricted meetings over every content path, the audit
log, exports, job monitoring, and reading results in the web app. Not tested here: features with
no API yet (registration, invitations, membership changes and password reset in US-001, US-002 and
US-020; notes regeneration, US-010; a workspace's own model provider, US-008; processing e-mails,
US-009; server load and model usage on the admin dashboard, US-019 Test-03); screens the web app
does not have yet (folders, transcript edits, shares, the glossary), so those are tested through the API
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
| TC-ACC-02 | Sessions and MCP keys over HTTP | Integration | Negative | A wrong password gets `401 INVALID_CREDENTIALS`; a request without a session, with a signed-out cookie or with a revoked or expired MCP key is refused; an MCP key is shown once and stored only as its hash. | Denys | US-001 (Test-02, Test-03), US-018 (Test-01, Test-03), NFR-012 | CI, exists |
| TC-ADM-01 | Admin & Monitoring: job monitoring | Integration | Negative | An administrator reads each job's state, waiting time and known failure reason, and nothing from a recording, transcript or notes; a workspace role grants no admin access, and a revoked administrator is refused at once. | Valeriia | US-019 (Test-01, Test-02, Test-04) | CI, exists |
| TC-PIPE-01 | Processing pipeline, upload to notes | Integration | Positive | Real PostgreSQL, RabbitMQ and SeaweedFS, stub ASR and notes models: a recording uploaded while no worker runs stays `queued`; once the workers start, the meeting reaches `processed` and the API returns one transcript and one set of notes. | Andrii | US-004 (Test-01), US-005 (Test-02), US-006 (Test-02), NFR-014 | CI, planned |
| TC-PIPE-02 | Processing pipeline, notes provider failure | Integration | Negative | A provider that refuses the key or the request: the meeting ends `failed` with `provider_rejected`, the transcript stays readable, no further notes job is queued. A provider unavailable on every attempt: at most 5 attempts (`MAX_ATTEMPTS`), then `failed` with `provider_unavailable`. | Andrii | US-004 (Test-03), NFR-014 | CI, planned |
| TC-NFR-01 | Processing pipeline, worker crash | Integration | Negative | The ASR worker is killed after it reports `job_started`; after a restart the meeting reaches `processed` with exactly one transcript (NFR-014: 100% of received meetings stay stored, visible and processable). | Andrii | NFR-014, US-004 | CI, planned; also on the GPU machine |
| TC-PROC-01 | Processing: repeated results | Unit | Negative | A duplicate or late result of a finished job queues nothing more and leaves the meeting unchanged. | Denys | NFR-014, US-004 | CI, exists |
| TC-PROC-02 | Processing: retry limit | Unit | Negative | A retryable failure past the attempt limit fails the meeting with its reason; the job is not published again. | Denys | US-004 (Test-03) | CI, exists |
| TC-MTG-02 | Meetings: accepting an upload | Integration | Positive | A supported file creates one `queued` meeting, a privately stored recording and one transcription job in the outbox; nothing is published inside the request. | Valeriia | US-004 (Test-01), NFR-014 | CI, exists |
| TC-NFR-04 | Core features during a processing outage | Integration | Positive | The API runs with no processing integration and no storage, which is how it sees a stopped worker, broker or LLM runtime. 20 requests go to each function NFR-015 names: sign-in, the workspace list, the meeting list, a processed meeting's transcript, and the sharing settings (its access and its shares). At least 95% of each function's requests succeed; any response but `2xx` counts as a failure. Recovery after the restart is TC-PIPE-01 and TC-NFR-01. | Andrii | NFR-015 | CI, exists |
| TC-AUD-01 | Audit: a change and its record | Unit | Positive | Renaming a meeting writes one audit event with the actor, the action and the meeting. | Denys | US-013, NFR-010 | CI, exists |
| TC-AUD-02 | Audit: every NFR-010 change the API offers | Integration | Positive | Meeting creation, renames, moves, deletions and evictions, transcript edits and speaker renames, notes regeneration, restrictions and grants, shares, share-request decisions, workspace deletion and MCP key changes each write exactly one record (actor, action type, target, time) in the same transaction, which a failed write rolls back; `details` holds no transcript, notes or recording content. Membership changes and provider configuration have no API yet. | Denys | NFR-010 | CI, exists |
| TC-AUD-03 | Audit: history cannot change | Integration | Negative | The application's database role cannot delete, update or truncate audit events, and an event survives its workspace's deletion. | Denys | NFR-010 | CI, exists |
| TC-MTG-01 | Meetings: upload validation | Unit | Negative | Bytes that do not decode as audio are refused with `415`, and no meeting is created. | Valeriia | US-004 (Test-02) | CI, exists |
| TC-NFR-02 | Meeting and workspace lists under load | System | Positive | k6, 50 virtual users for 30 s per list endpoint, one uvicorn worker: p95 at most 200 ms and no failed request, the API's share of NFR-001's 2-second page budget (QA-1). It does not time a page in the browser, so NFR-001 is covered only in part. | Zlata | NFR-001, US-013 | Manual, `tests/performance/test_lists.js` with k6 from its Docker image |
| TC-WS-01 | Accounts: creating and deleting a workspace | Integration | Positive | A new workspace has its creator as Owner and a default folder; a Member cannot delete a workspace, and nobody can delete a personal one. | Denys | US-002 (Test-01, Test-04) | CI, exists |
| TC-ACL-03 | Access Policy: who may restrict | Unit | Negative | A Member cannot restrict a meeting or change its access list, and access cannot be granted to someone outside the workspace. | Valeriia | US-015 (Test-04) | CI, exists |
| TC-SHR-01 | Access Policy: external shares | Integration | Negative | A share only reads: no export, recording, MCP or edit. It binds to the one approved account, the creator gets the access request, and a declined or revoked share reads nothing; a redacted share names the speakers Speaker 1, Speaker 2. | Valeriia | US-016 (Test-01, Test-03 to Test-06), NFR-008 | CI, exists |
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
| TC-NOTES-01 | 2026-10-25 | `0a7db9f` | Ollama in Compose, `gemma4:12b-it-qat` | Pass, 4 of 4 | 138 s, mostly model loading | None |
| TC-NFR-03 | 2026-10-25 | `a8eb270` (#151); the first run `bea46c7` | GPU machine (i5-10400F, RTX 4070 12 GB, WSL2), Compose with `compose.cuda.yaml`: pyannote community-1 on the GPU, Parakeet TDT 0.6B v3 int8 on the CPU, 1 slot | Pass, 3 of 3 | Queued to transcript ready in 434 s, 425 s and 437 s, against 900 s. The first run spent 67 s in pyannote and 351 s in Parakeet. Notes came from 1 part at `num_ctx` 32768 and from 4 parts at 20480 | Without a GPU it misses: transcription takes 0.70–0.74 of the recording's length (#150) |

## AI Usage

Drafted with Claude Code (Claude Opus 5.5) from Zlata's initial draft (OpenAI Codex) and the GPU
machine runs, and checked against the code at `fb5cbc6`. The team reviews it before merging.
