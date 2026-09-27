# Traceability Matrix

Architectural view of the requirements in [rtm.md](../requirements/rtm.md) and [requirements.md](../requirements/requirements.md): requirement → component → design decision → verification, against the components of the [high-level design](high-level-design.md).

## 1. Requirements → Architecture

### User stories

| Story | FRs | Components | Design decision | Verification |
|---|---|---|---|---|
| US-001 Register and sign in | FR-001, FR-002, FR-003, FR-004 | Accounts & Workspaces, Access Policy | Registration creates the user, a personal workspace and its default folder; every content request needs a session | API test: anonymous → denied |
| US-002 Manage a workspace | FR-005, FR-006, FR-007, FR-008 | Accounts & Workspaces, Access Policy | Membership has a role (owner, moderator, member); role changes are logged; personal workspaces refuse deletion | Role-by-role API tests |
| US-003 Record from the browser | FR-009, FR-010, FR-011, FR-012 | Google Meet tab, Chrome extension, Capture, Object storage, Meetings, Processing | Consent confirmed before recording; chunks saved as they arrive; the finished recording becomes a queued meeting | Manual test on Meet |
| US-004 Upload a recording | FR-013, FR-014 | Capture, Object storage, Processing | Upload shares the extension's ingest path; failed jobs keep their state | Integration test |
| US-005 Transcript by speaker | FR-015, FR-016, FR-017 | Transcription pipeline, Chrome extension, Processing, Meetings | ASR with speaker separation; the extension reads names from the Meet participant list | Diarization error rate (DER) benchmark; test that extension recordings get participant names and uploads get "Speaker N" |
| US-006 Notes from a preset | FR-018 | Notes pipeline, LLM runtime, Processing | Fixed presets (summary, detailed, interview) stored server-side; Processing puts the preset into the job | Unit test |
| US-007 Folder as context | FR-019, FR-020 | Notes pipeline, Access Policy | Context = same folder, filtered by Access Policy; used meetings saved with notes | Test with a restricted meeting in the folder |
| US-008 Own model provider | FR-021, FR-022, FR-023 | Notes pipeline, LLM provider, Accounts & Workspaces, Processing | Fixed provider list; key visible to the Owner only; on provider failure the meeting is shown as failed with the cause and generation with the built-in model is offered | Egress test; simulated provider failure |
| US-009 Processing notifications | FR-024 | Processing, Notifications, SMTP relay | Email carries a link only, no content | Test with a mail catcher |
| US-010 Regenerate notes | FR-025, FR-026 | Processing, Meetings | Regeneration limit; old notes kept; failed run changes nothing | Unit test |
| US-011 Correct the transcript | FR-027, FR-028 | Meetings, Web SPA, Object storage | Edits create a new version; original kept; playback via presigned URL | API and E2E tests |
| US-012 Workspace glossary | FR-029, FR-030 | Meetings, Transcription pipeline, Processing | Processing passes the workspace glossary to recognition | Accuracy with vs without glossary |
| US-013 Browse and filter | FR-031, FR-032, FR-033 | Web SPA, Meetings | Paged list; name and date filters | API and E2E tests |
| US-014 Folders, move, delete | FR-034, FR-035, FR-036 | Meetings, Access Policy | Flat folders; deleting a folder moves meetings to default | Integration test |
| US-015 Restrict a meeting | FR-037 | Access Policy | One check point for lists, links, MCP and context | Test every path |
| US-016 Share read-only | FR-038, FR-039 | Access Policy, Meetings | Revocable read-only share; optional name redaction | API test |
| US-017 Export | FR-040, FR-041, FR-042 | Export, Meetings, Access Policy | Current version, "edited" marker, notice and attribution | Reference-file tests |
| US-018 Own AI assistant | FR-043, FR-044 | MCP client, MCP Server, Accounts & Workspaces, Access Policy | Keys shown once, stored hashed; results filtered by Access Policy | Unit and API tests |
| US-019 Admin dashboard | FR-045 | Admin & Monitoring, Processing | Reads job states from Processing and system metrics only, no content | Query review |
| Retention policy (referenced in US-011) | FR-046 | Retention, Notifications | Scheduled deletion of recordings three months after the meeting; Notifications warns members in advance | Test with a mocked clock |

### Non-functional requirements

| Req | Components | Design decision | Verification |
|---|---|---|---|
| NFR-001 Page speed | Meetings, PostgreSQL | Paging and indexes | Load test: 90% under 2 s |
| NFR-002 Transcription time | Transcription pipeline | Dedicated GPU, async jobs | Benchmark: 1 h audio, 90% under 15 min |
| NFR-003 Capacity | Meetings | The cap is checked when Meetings creates a meeting, in the same transaction; the oldest meeting is deleted through the same path as FR-036; the limit is a setting (1000 on the hosted service, none when self-hosted) | Integration test: creating the 1001st meeting deletes the oldest together with its recording, transcript and notes, and two concurrent creations don't exceed the cap |
| NFR-004 Co-existence | Chrome extension | Captures audio without joining the call | Manual test |
| NFR-005, NFR-006, NFR-011 Versions | Meetings | Versioned transcripts and notes | API test |
| NFR-007, NFR-008, NFR-009 Confidentiality | Access Policy | Single enforcement point on every content path | Authorization test matrix |
| NFR-010 Accountability | Accounts & Workspaces, PostgreSQL | Audit log with account ID. Pending team decision on a dedicated Audit module (append-only events, account ID only, written in the same transaction as the change) | Integration test per action type, including that deleting a meeting leaves its deletion event behind |
| NFR-012 Authenticity | Accounts & Workspaces | Hashed passwords, HTTPS, sessions | Security checklist |
| NFR-013 Key secrecy | Accounts & Workspaces, Access Policy | Provider key visible to the Owner only | Role test |
| NFR-014 Recoverability | Object storage, Message broker | Audio saved before processing; queued jobs persist | Stop workers, upload, restart |
| NFR-015 Fault tolerance | Message broker, Transcription pipeline, Notes pipeline | Process isolation: ML work runs in separate worker processes that the backend reaches only through the broker | Kill workers, check web stays up |
| NFR-016, NFR-017 Portability | All runtime units | One image, Compose profiles core and gpu | Fresh install from docs |

### Reverse check

Every component in the [component diagram](uml/component-diagram.svg) appears in at least one row above.

## 2. Quality attribute scenarios

### Scenario 1: Transcription time

> A member uploads a 1-hour recording. Processing sends it through the broker to the
> transcription pipeline. The transcript is visible within **15 minutes in 90% of runs**,
> before the notes are ready.

**Verification:** benchmark on the reference GPU host: at least 20 recordings of about 1 h,
submitted one at a time with no other jobs queued; passes if at least 90% have a transcript within
15 min of upload.

**Covers:** NFR-002 · **Components:** Processing → Message broker → Transcription pipeline

### Scenario 2: Restricted meeting

> A member who is not allowed to see a restricted meeting tries to open it through a direct link,
> through their AI assistant, and indirectly through another meeting's notes. Access Policy
> denies every path. **Zero content leaks** across the authorization test matrix.

**Covers:** NFR-007, NFR-009 · **Components:** Access Policy, Meetings, MCP Server, Notes pipeline

### Scenario 3: GPU host failure

> The GPU host stops in the middle of a transcription job. The web app keeps serving reads and
> new uploads are accepted. After the host returns, the job is re-delivered and completes.
> **Zero meetings lost.**

**Verification:** chaos test: stop the GPU host during a running transcription job, check reads
and a new upload succeed, restart the host, and confirm both jobs complete.

**Covers:** NFR-014, NFR-015 · **Components:** Message broker, Object storage, Processing, Transcription pipeline

## AI Usage

Drafted with Claude Code (Claude Opus 5.5) from requirements.md, rtm.md, the component diagram
and the 2026-09-26 architecture review. Reviewed by the team before merging.
