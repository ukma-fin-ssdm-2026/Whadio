# Traceability Matrix

Architectural view of the requirements in [rtm.md](../requirements/rtm.md) and [requirements.md](../requirements/requirements.md): requirement → component → design decision → verification, against the components of the [high-level design](high-level-design.md).

## 1. Requirements → Architecture

### User stories

| Story | FRs | Components | Design decision | Verification |
|---|---|---|---|---|
| US-001 Register and sign in | FR-001, FR-002, FR-003, FR-004, FR-047, FR-049 | Accounts & Workspaces, Access Policy, Notifications, SMTP relay | Email-first registration: the user, a personal workspace and its default folder are created only once the emailed link is opened; a repeated request within 20 minutes changes nothing; there is no open registration in `invite-only` mode, and the operator issues links from the command line; every content request needs a session | API test: anonymous → denied; registration tests with a mail catcher |
| US-002 Manage a workspace | FR-002, FR-005, FR-006, FR-007, FR-008 | Accounts & Workspaces, Access Policy, Audit, Notifications, SMTP relay | Membership has a role (owner, moderator, member); membership and role changes are recorded as audit events; personal workspaces refuse deletion; invitations are single-use links for the invited address, emailed or handed over by the Moderator; pending invitations can be cancelled, stop working once their creator loses the Moderator role, and are limited per day | Role-by-role API tests; invitation tests with a mail catcher |
| US-003 Record from the browser | FR-009, FR-010, FR-011, FR-012 | Google Meet tab, Chrome extension, Capture, Object storage, Meetings, Processing | Consent confirmed before recording; chunks saved as they arrive; the finished recording becomes a queued meeting | Manual test on Meet |
| US-004 Upload a recording | FR-013, FR-014 | Capture, Object storage, Processing | Upload shares the extension's ingest path; failed jobs keep their state | Integration test |
| US-005 Transcript by speaker | FR-015, FR-016, FR-017 | Transcription pipeline, Chrome extension, Processing, Meetings | ASR with speaker separation; the extension reads names from the Meet participant list | Diarization error rate (DER) benchmark; test that extension recordings get participant names and uploads get "Speaker N" |
| US-006 Notes from a preset | FR-018 | Notes pipeline, LLM runtime, Processing | Fixed presets (summary, detailed, interview) stored server-side; Processing puts the preset into the job | Unit test |
| US-007 Folder as context | FR-019, FR-020 | Processing, Notes pipeline, Access Policy | Context = same folder, filtered by Access Policy; used meetings saved with notes | Test with a restricted meeting in the folder |
| US-008 Own model provider | FR-021, FR-022, FR-023 | Notes pipeline, LLM provider, Accounts & Workspaces, Processing | Fixed provider list; key visible to the Owner only; on provider failure the meeting is shown as failed with the cause and generation with the built-in model is offered | Egress test; simulated provider failure |
| US-009 Processing notifications | FR-024 | Processing, Notifications, SMTP relay | Email carries a link only, no content | Test with a mail catcher |
| US-010 Regenerate notes | FR-025, FR-026 | Processing, Meetings | Regeneration limit; old notes kept; failed run changes nothing | Unit test |
| US-011 Correct the transcript | FR-027, FR-028 | Meetings, Web SPA, Object storage | Edits create a new version; original kept; playback via presigned URL | API and E2E tests |
| US-012 Workspace glossary | FR-029, FR-030 | Meetings, Transcription pipeline, Processing | Processing passes the workspace glossary to recognition | Accuracy with vs without glossary |
| US-013 Browse, name and filter | FR-031, FR-032, FR-033 | Web SPA, Meetings, Notes pipeline, Processing | Paged list; name and date filters | API and E2E tests |
| US-014 Folders, move, delete | FR-034, FR-035, FR-036 | Meetings, Access Policy | Flat folders; deleting a folder moves meetings to default | Integration test |
| US-015 Restrict a meeting | FR-037 | Access Policy | One check point for lists, links, MCP and context | Test every path |
| US-016 Share read-only | FR-038, FR-039, FR-047 | Access Policy, Meetings, Notifications, SMTP relay | Revocable read-only share; the link yields an access request, and the share is bound to the account its creator approves; optional name redaction; a share link never creates an account | API test; test with a mail catcher |
| US-017 Export | FR-040, FR-041, FR-042 | Export, Meetings, Access Policy | Current version, "edited" marker, notice and attribution | Reference-file tests |
| US-018 Own AI assistant | FR-043, FR-044 | MCP client, MCP Server, Accounts & Workspaces, Access Policy | Keys shown once, stored hashed; results filtered by Access Policy | Unit and API tests |
| US-019 Admin dashboard | FR-045 | Admin & Monitoring, Processing | Reads job states from Processing and system metrics only, no content | Query review |
| US-020 Reset a forgotten password | FR-048, FR-049 | Accounts & Workspaces, Notifications, SMTP relay | Single-use emailed link; a new password ends every earlier session and extension token; requested by users only in `verified` mode, and issued by the operator in either | API tests with a mail catcher and a mocked clock |
| Retention policy (referenced in US-011) | FR-046 | Retention, Notifications | Scheduled deletion of recordings three months after the meeting; Notifications warns members in advance | Test with a mocked clock |

### Non-functional requirements

| Req | Components | Design decision | Verification |
|---|---|---|---|
| NFR-001 Page speed | Meetings, PostgreSQL | Paging and indexes | Load test: 90% under 2 s |
| NFR-002 Transcription time | Transcription pipeline | Dedicated GPU, async jobs | Benchmark: 1 h audio, 90% under 15 min |
| NFR-003 Capacity | Meetings, Notifications | When a meeting is queued, Meetings counts the queued and later meetings across the workspaces of its workspace's Owner, under a per-Owner lock in the same transaction; above the cap, the earliest-created of them is deleted with the same cascade as FR-036, and its recording is removed from object storage after the commit; Notifications tells the triggering member and the evicted meeting's creator, naming the meeting only to a recipient who could read it; the limit is a setting (1000 on the hosted service, none when self-hosted) | Integration tests at the cap: queuing a meeting deletes the Owner's earliest-created meeting together with its recording, transcript and notes, also when it sits in another workspace; a meeting still recording neither counts nor is evicted; two meetings queued concurrently in two of the Owner's workspaces leave exactly 1000; a notice to a recipient who could not read the evicted meeting omits its name |
| NFR-004 Co-existence | Chrome extension | Captures audio without joining the call or disrupting normal Meet controls | 5 supported-Chrome recordings of at least 10 min; pass if no extra participant appears, the Meet tab does not crash, and mute/unmute/speaking/hearing/stop recording all keep working |
| NFR-005, NFR-006, NFR-011 Versions | Meetings | Versioned transcripts and notes; reversible moves, folder deletion and note regeneration | API/E2E tests: restoration in no more than 3 actions for reversible actions; edited marker and original version reachable in no more than 2 actions on 100% edited transcript views/exports |
| NFR-007, NFR-008, NFR-009 Confidentiality | Access Policy | Single enforcement point on every content path, including shares and MCP | Authorization test matrix over 100% content-returning endpoints and content paths; pass if unauthorized identities receive zero recording, transcript or notes content |
| NFR-010 Accountability | Audit, written by Meetings, Access Policy and Accounts & Workspaces | Append-only audit events with the actor's account ID, action type, target IDs and timestamp, never content; written in the same transaction as the change by the module that performs it; no foreign keys to the meeting or workspace; the table is owned by the migration role, and the application role may only insert and select ([ADR-005](decisions/ADR-005.md)) | Integration test per action type; pass if 100% of the listed changes create an audit record without transcript, note or recording content, deleting a meeting or a workspace leaves its events behind, and updating or deleting an audit record as the application role is refused |
| NFR-012 Authenticity | Accounts & Workspaces | Hashed passwords, HTTPS, server-side sessions stored as token hashes, MCP key revocation | Authentication test suite; pass if 100% of wrong passwords, missing sessions and revoked MCP keys are rejected, and stored passwords are hashes only |
| NFR-013 Key secrecy | Accounts & Workspaces, Access Policy | Provider key encrypted at rest and visible only to the Owner at creation/configuration time | Role and response-shape tests; pass if 100% of non-Owner requests return no key material and no API response returns a raw provider key after creation |
| NFR-018 Authenticity of email addresses | Accounts & Workspaces, Notifications | Accounts are created only from an opened link, an invitation or an operator's link; identical responses for known and unknown addresses; a 20-minute cooldown per address, read from the existing registration or reset row; per-day invitation limits counted from invitation rows | API tests; pass if 100% of used, expired or cancelled links are rejected, responses for known and unknown addresses match, a request within the cooldown sends nothing and leaves the earlier link working, and invitations beyond the daily limits are refused |
| NFR-014 Recoverability | Object storage, Message broker | Audio saved before processing; queued jobs persist and can resume | Chaos test: stop a processing component during a job, verify 100% received meetings remain stored and process after restart |
| NFR-015 Fault tolerance | Message broker, Transcription pipeline, Notes pipeline | Process isolation: ML work runs in separate worker processes that the backend reaches only through the broker | Kill transcription worker, notes worker and LLM runtime in separate tests; pass if at least 95% of unrelated requests complete successfully |
| NFR-016, NFR-017 Portability | All runtime units | One image, Compose profiles `core` and `gpu`; no source-code changes between single-host and two-host profiles | Release smoke test starts all required containers in the single-host profile; fresh-install test on a clean Docker machine reaches the web UI within 30 min with no source-code edits |

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

**Verification:** authorization test matrix: for a restricted meeting, request it as a
non-selected member through the meeting list, a direct link, the MCP server with that member's
key, and as context for notes of another meeting in the same folder; passes if every request
returns no content and the meeting is absent from the recorded context set.

**Covers:** NFR-007, NFR-009 · **Components:** Access Policy, Meetings, MCP Server, Notes pipeline

### Scenario 3: GPU host failure

> The GPU host stops in the middle of a transcription job. The web app keeps serving reads and
> new uploads are accepted. After the host returns, the job is re-delivered and completes.
> **Zero meetings lost.**

**Verification:** chaos test: stop the GPU host during a running transcription job, check reads
and a new upload succeed, restart the host, and confirm both jobs complete.

**Covers:** NFR-014, NFR-015 · **Components:** Message broker, Object storage, Processing, Transcription pipeline

## AI Usage

Drafted and revised with Claude Code (Claude Opus 5.5) from requirements.md, rtm.md, the component
diagram and the 2026-09-26 architecture review. Reviewed by the team before merging.
