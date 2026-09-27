 ## 1. Requirements → Architecture

| Story | Components | Design decision | Verification |
|---|---|---|---|
| US-001 Register and sign in | Web API, Accounts & Workspaces, Access Policy | Registration creates the user, a personal workspace and its default folder; every content request needs a session | API test: anonymous → denied |
| US-002 Manage a workspace | Accounts & Workspaces, Access Policy | Membership has a role (owner, moderator, member); role changes are logged; personal workspaces refuse deletion | Role-by-role API tests |
| US-003 Record from the browser | Chrome extension, Capture API, Object storage | Consent confirmed before recording; chunks saved as they arrive | Manual test on Meet |
| US-004 Upload a recording | Capture API, Object storage, Processing | Upload shares the extension's ingest path; failed jobs keep their state | Integration test |
| US-005 Transcript by speaker | Transcription pipeline, Meetings | ASR with speaker separation; names from the Meet participant list | Accuracy (WER) benchmark |
| US-006 Notes from a preset | Notes pipeline, LLM runtime | Fixed presets (summary, detailed, interview) stored server-side | Unit test |
| US-007 Folder as context | Notes pipeline, Access Policy | Context = same folder, filtered by Access Policy; used meetings saved with notes | Test with a restricted meeting in the folder |
| US-008 Own model provider | Notes pipeline, LLM provider, Accounts & Workspaces | Fixed provider list; key visible to the Owner only; fall back to built-in on failure | Egress test; simulated provider failure |
| US-009 Processing notifications | Processing, Notifications, SMTP relay | Email carries a link only, no content | Test with a mail catcher |
| US-010 Regenerate notes | Processing, Meetings | Regeneration limit; old notes kept; failed run changes nothing | Unit test |
| US-011 Correct the transcript | Meetings, Web SPA, Object storage | Edits create a new version; original kept; playback via presigned URL | API and E2E tests |
| US-012 Workspace glossary | Meetings, Transcription pipeline | Glossary passed to recognition | Accuracy with vs without glossary |
| US-013 Browse and filter | Web SPA, Web API, Meetings | Paged list; name and date filters | API and E2E tests |
| US-014 Folders, move, delete | Meetings, Access Policy | Flat folders; deleting a folder moves meetings to default | Integration test |
| US-015 Restrict a meeting | Access Policy | One check point for lists, links, MCP and context | Test every path |
| US-016 Share read-only | Access Policy, Meetings | Revocable read-only share; optional name redaction | API test |
| US-017 Export | Export | Current version, "edited" marker, notice and attribution | Reference-file tests |
| US-018 Own AI assistant | MCP Server, Accounts & Workspaces, Access Policy | Keys shown once, stored hashed; results filtered by Access Policy | Unit and API tests |
| US-019 Admin dashboard | Admin & Monitoring, Message broker | Reads only queue and system metrics | Query review |

| Req | Components | Design decision | Verification |
|---|---|---|---|
| NFR-001 Page speed | Web API, PostgreSQL | Paging and indexes | Load test: 90% under 2 s |
| NFR-002 Transcription time | Transcription pipeline | Dedicated GPU, async jobs | Benchmark: 1 h audio, 90% under 15 min |
| NFR-003 Capacity | Meetings, Retention | Limit checked on ingest, oldest meeting evicted | Integration test |
| NFR-004 Co-existence | Chrome extension | Captures audio without joining the call | Manual test |
| NFR-005, 006, 011 Versions | Meetings | Versioned transcripts and notes | API test |
| NFR-007 – 009 Confidentiality | Access Policy | Single enforcement point on every content path | Authorization test matrix |
| NFR-010 Accountability | Accounts & Workspaces, PostgreSQL | Audit log with account ID | Integration test |
| NFR-012 Authenticity | Accounts & Workspaces | Hashed passwords, HTTPS, sessions | Security checklist |
| NFR-013 Key secrecy | Accounts & Workspaces, Access Policy | Provider key visible to the Owner only | Role test |
| NFR-014 Recoverability | Object storage, Message broker | Audio saved before processing; queued jobs persist | Stop workers, upload, restart |
| NFR-015 Fault tolerance | Message broker, deployment | Workers on a separate machine | Kill workers, check web stays up |
| NFR-016, 017 Portability | Docker Compose | Documented two-machine setup | Fresh install from docs |

## 2. Quality attribute scenarios
1.

> A member uploads a 1-hour recording under normal load. Processing sends it through the broker
> to the transcription pipeline. The transcript is visible within **15 minutes in 90% of runs**,
> before the notes are ready.

**Covers:** NFR-002 · **Components:** Processing → Message broker → Transcription pipeline

2.

> A member who is not allowed to see a restricted meeting tries to open it through a direct link,
> through their AI assistant, and indirectly through another meeting's notes. Access Policy
> denies every path. **Zero content leaks** across the authorization test matrix.

**Covers:** NFR-007, NFR-009 · **Components:** Access Policy, Meetings, MCP Server, Notes pipeline

## AI Usage

Drafted with Claude Code (Claude Opus 5.5) from requirements.md, rtm.md, the component diagram
and the 2026-09-26 architecture review. Reviewed by the team before merging.
