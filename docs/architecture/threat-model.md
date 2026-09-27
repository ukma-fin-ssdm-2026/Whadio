# Whadio Threat Model

This document applies STRIDE to the production deployment diagram in [`uml/deployment-diagram.puml`](uml/deployment-diagram.puml). The diagram marks trust zones and boundary labels (`TB-1` through `TB-8`).

## Scope

The model covers the Chrome extension, web SPA, MCP client, Google Meet page, nginx, backend web container, scheduler, notes worker, RabbitMQ, PostgreSQL, object storage, GPU host, ASR worker, local LLM runtime, external LLM providers, and SMTP relay.

The most sensitive assets are meeting recordings and capture chunks, transcripts, speaker labels, notes, note context records, workspace membership and roles, invitation emails, external share tokens, MCP keys, provider API keys, and processing metadata.

## Trust Boundaries

| ID | Boundary | Data crossing it | Why trust changes |
| --- | --- | --- | --- |
| `TB-1` | Browser or MCP client to nginx | Sessions, uploads, API calls, MCP requests, meeting content | User-controlled devices and external clients call the public Whadio entry point. |
| `TB-2` | Extension to Google Meet page | Participant names and active-speaker events | The extension reads a third-party page outside Whadio control. |
| `TB-3` | nginx to web container | Authenticated HTTP requests | Public traffic becomes internal application traffic after TLS termination. |
| `TB-4` | Web/scheduler to PostgreSQL and object storage | Metadata, recordings, chunks, transcripts, notes, keys, shares | Application code crosses into persistent storage. |
| `TB-5` | Web/scheduler/workers to RabbitMQ | Processing jobs and status events | Components trust broker messages to start expensive work or update state. |
| `TB-6` | Main host to GPU host | AMQP traffic, presigned audio URLs, local LLM requests | Processing moves across hosts over the private network. |
| `TB-7` | Notes worker to external LLM provider | Transcript and context text, BYOK credential use | Meeting content leaves Whadio only when configured by a workspace Owner. |
| `TB-8` | Web container to SMTP relay | Notification metadata and email addresses | Whadio depends on an external mail service. |

## STRIDE Walkthrough

| Target | S | T | R | I | D | E |
| --- | --- | --- | --- | --- | --- | --- |
| Chrome extension and SPA | Stolen session, malicious local client | Upload/content modified before sending | User denies recording, upload, edit, share | Local browser leaks content | Large uploads or repeated calls | Client-side role checks bypassed |
| Google Meet DOM boundary | Fake participant names | Page layout or injected DOM changes labels | No proof of captured names | Extension reads more DOM data than needed | Meet UI changes break capture | Extension permission abuse |
| nginx public entry point | Credential/session spoofing | Request tampering without TLS | Missing access logs | Protected content routed incorrectly | Request flood or slow uploads | Proxy exposes internal paths |
| Web backend | Impersonated user/service | Broken validation changes meetings, roles, shares | Missing audit records | Authorization bugs leak meetings | Expensive processing or export requests | Workspace role bypass |
| PostgreSQL and object storage | Stolen service credentials | Direct row/object modification | No protected audit trail | Database or recording leak | Storage exhaustion | Overbroad service account |
| RabbitMQ | Fake worker or publisher | Forged job/result message | Worker denies processing a job | Queue messages expose paths/metadata | Queue flood blocks processing | Worker receives unauthorized job scope |
| GPU host and workers | Fake main host or worker | Model output/job tampering | Missing job execution evidence | Presigned URL or transcript leak | GPU exhaustion | Worker gains broader storage access |
| Local LLM runtime | Fake runtime endpoint | Prompt/result manipulation | No trace of model version/result | Transcript leaks through logs | Long prompts exhaust runtime | Runtime container escape |
| External LLM provider | Provider/API spoofing | Response manipulation | Provider call cannot be traced | Transcript/context disclosure | Provider outage or rate limit | Provider key misuse |
| SMTP relay | Relay spoofing | Notification content changed | Delivery dispute | Email address or metadata leak | Mail outage/rate limit | Relay credentials abused |
| MCP client boundary | Stolen MCP key | Tool request tampering | Assistant/user denies access | Assistant receives unauthorized meetings | Automated scraping | MCP key grants too much scope |

## Identified Risks

| ID | Component or boundary | STRIDE category | Scenario | Rating | Planned countermeasure or accepted decision |
| --- | --- | --- | --- | --- | --- |
| `R-01` | `TB-1` browser/MCP client to nginx | Spoofing | An attacker steals a browser session cookie or MCP key and accesses meetings as the victim. | High | Use secure, HttpOnly, SameSite session cookies; hash MCP keys; show MCP keys only once; support revocation; rate-limit failed authentication; require authentication on every content endpoint. |
| `R-02` | Web backend authorization | Elevation of privilege | A Member calls an API endpoint intended for Moderator, Owner, or Administrator actions, such as restricting a meeting, managing members, configuring a provider key, or reading monitoring data. | High | Enforce role checks server-side through a single access policy layer; cover content and administration endpoints with authorization tests; ignore client-side role state for decisions. |
| `R-03` | `TB-4` app to PostgreSQL/object storage | Information disclosure | A bug or overly broad presigned URL exposes a recording, capture chunk, transcript, or note to a user without meeting access. | High | Keep object storage private; issue short-lived presigned URLs only after access checks; never expose raw storage paths; use unguessable object keys; log access decisions without logging content. |
| `R-04` | Transcript revision and speaker labels | Tampering | Edited transcript text or renamed speaker labels overwrite the original record, making changed content appear original. | High | Store immutable original revisions; save text edits and speaker-label changes as edited revisions; display and export an edited marker; enforce that current revisions belong to the same transcript. |
| `R-05` | `TB-7` external LLM provider | Information disclosure | When an Owner configures BYOK, transcript and folder-context text are sent to a third-party provider and may leave Whadio's privacy boundary. | High | Make BYOK opt-in and Owner-only; clearly show when provider mode is active; send only required context; store provider keys encrypted; treat this as an explicit Owner disclosure decision. |
| `R-06` | RabbitMQ and processing jobs | Tampering | A forged or replayed queue message marks processing as successful, attaches output to the wrong meeting, or starts processing with a stale presigned URL. | Medium | Authenticate broker connections; isolate queues on the private network; include meeting/job IDs and expected state transitions; reject stale or duplicate job events; keep processing updates idempotent. |
| `R-07` | Upload and processing pipeline | Denial of service | A user uploads many large files or repeatedly regenerates notes, exhausting disk, queue capacity, CPU, GPU, or LLM runtime. | High | Enforce file size, duration, per-user meeting limits, and note-regeneration limits; cap concurrent jobs; rate-limit uploads; show queue backpressure in monitoring; keep unrelated web features available. |
| `R-08` | `TB-2` extension to Google Meet page | Tampering | Google Meet DOM changes or malicious page manipulation causes wrong speaker names or active-speaker events to be stored. | Medium | Treat Meet-derived names and speaker events as untrusted hints; allow speaker-label correction through edited revisions; fall back to generic Speaker N labels when extraction is unreliable; never use DOM labels for authorization. |
| `R-09` | External share links | Information disclosure | A share token leaks or a recipient forwards a link, exposing transcript and notes outside the intended audience. | Medium | Store only token hashes; require sign-in for share access; allow revocation; restrict shares to read-only transcript/notes; remove recording from redacted shares; audit share creation and access. |
| `R-10` | Audit trail for content and access changes | Repudiation | A user denies editing a transcript, renaming speakers, restricting a meeting, creating a share, changing membership, or configuring an external provider. | Medium | Record actor, timestamp, target entity, and action type for content, access, share, provider, MCP key, and membership changes; protect audit records from ordinary user modification. |
| `R-11` | `TB-8` SMTP relay | Information disclosure | Notification emails reveal meeting titles, workspace names, processing failures, or links to unintended recipients. | Low | Send notification metadata only, never transcript/note/recording content; verify recipient addresses; use STARTTLS; keep links behind sign-in and access checks. |
| `R-12` | GPU host and presigned URLs | Elevation of privilege | A compromised worker reuses presigned URLs or obtains broader storage/database access than needed. | Medium | Keep GPU host without public ports; avoid database credentials on the GPU host; use short-lived presigned URLs scoped to one object and operation; rotate credentials; monitor unusual object access. |

## Accepted Risks

| Risk | Decision |
| --- | --- |
| Google Meet DOM instability | Accepted for this version. There is no official Meet API in scope, so speaker extraction can fail or become inaccurate. The fallback is generic speaker labels plus manual correction. |
| Single-main-host availability | Accepted for the semester scope. The project has no uptime guarantee; processing failures must be isolated so unrelated functionality remains usable when workers fail. |
| Owner-controlled BYOK disclosure | Accepted as an explicit workspace Owner choice. The UI and documentation must state that provider mode sends transcript context to the configured external provider. |

## Security Requirements Derived From This Model

- All meeting content paths, including web UI, direct links, shares, exports generated on request, and MCP, must call the same server-side access policy.
- Credentials and tokens must be stored only as hashes or encrypted secrets, never as plaintext.
- Recording and chunk object access must be mediated by short-lived, access-checked URLs.
- Processing and note-generation jobs must be authenticated, idempotent, and tied to explicit meeting/job state.
- Audit records are required for content edits, speaker-label changes, access changes, shares, provider configuration, MCP keys, and membership changes.
- Logs and monitoring must avoid storing recordings, transcript text, notes, raw keys, raw share tokens, or provider credentials.

## AI Usage

This threat model was prepared with the assistance of Codex (GPT-5.5) and reviewed against the project requirements, the high-level design, the deployment diagram, and the current data model.
