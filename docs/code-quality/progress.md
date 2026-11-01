# Implementation Progress

State on 2026-11-01 at `main` commit `46af4d7`, for the midterm evaluation.

## Try the current product

Whadio has no public evaluation instance yet; deployment is tracked in
[#182](https://github.com/ukma-fin-ssdm-2026/Whadio/issues/182). The current product can be run
locally with the [README setup](../../README.md#development), and recordings are processed after
starting the [workers](../../README.md#running-the-workers). The dedicated midterm demo is tracked
in [#192](https://github.com/ukma-fin-ssdm-2026/Whadio/issues/192).

## End-to-end path

The implemented path starts either in the Chrome extension or with an upload in the SPA. The
recording goes to S3-compatible storage, Processing publishes a RabbitMQ job, the ASR worker
creates a speaker-separated transcript, and the notes worker writes notes through local Ollama or
Anthropic. Processing stores each result, the SPA polls the meeting until it is ready, and the user
can play the recording, read the transcript and notes, and export them.

The production Compose template runs nginx, migrations, the API, scheduler, both workers,
PostgreSQL, RabbitMQ and optional SeaweedFS on one CPU host by default. A CUDA override accelerates
ASR, and an optional Ollama profile supplies the built-in notes model.

## Feature status

| Feature area | Built | Partial or missing |
|---|---|---|
| Accounts and workspaces | Stored accounts and Argon2id passwords; browser and extension sessions; workspace create, read, update and delete; operator registration and password-reset links; invitation creation, preview, acceptance, registration, decline and cancellation | Self-service registration and reset requests by email; SPA pages for registration, reset, invitations and member management; member role/removal API |
| Capture and upload | Chrome extension consent flow, tab and microphone recording, chunk upload and completion; existing-file upload; storage validation and queued processing | Interrupted captures are not finalised by the scheduler; extension publication to the Chrome Web Store is out of scope |
| Processing and workers | Transactional job outbox, least-privilege broker users, retries and failure reasons; Parakeet or Whisper recognition; pyannote diarization; Claude or Ollama notes; CPU and CUDA configurations | The planned full-system CI cases TC-PIPE-01, TC-PIPE-02 and TC-NFR-01 do not exist yet; the public CPU-host timing required by #182 has not been run |
| Meetings and organisation | Meeting lists, name/date filters, rename, delete, playback, folders with restore, glossary CRUD, transcript revisions and speaker renaming | Folder and glossary management are API-only; notes regeneration is deliberately refused for the MVP; cross-meeting context is not implemented |
| Access and sharing | Workspace and restricted access, explicit grants, shares, access requests and decisions, recipient content views, redacted speaker labels, authorization shared by HTTP and MCP | Sharing and access management have no SPA screens |
| Notes and export | Notes rendered safely as Markdown; current/original transcript export to Markdown or VTT; notes export to Markdown | Workspace-specific provider-key management is designed but not implemented; editable notes are out of scope |
| MCP | Personal keys shown once and stored hashed; meeting search/list, transcript and notes tools enforce the same access policy | Authentication rate limiting remains a tracked security follow-up |
| Retention and notifications | Recording expiry and deletion, deletion warnings, processing outcome notices, transactional notification outbox and SMTP delivery; expired registration, invitation and reset-link cleanup | No SMTP relay means notices remain unsent by design in `invite-only` mode |
| Administration | Admin permission CLI; API job list and aggregate metrics with no meeting content | No administrator SPA dashboard; host/model telemetry is not collected |
| Web SPA | Sign-in/out, workspace and all-meeting libraries, filters in the URL, upload, processing-state polling, playback, notes, transcript revision viewing and search, export, workspace defaults and MCP key management | The account, membership, folder, glossary, sharing, access and administrator surfaces listed above remain API-only |
| Deployment and operations | Development and production Compose configurations, TLS nginx proxy, health checks, one-shot migrations, external or bundled S3-compatible storage, CPU/CUDA ASR and local/external notes provider choices | `https://whadio.com`, automated deployment/rollback and the operating note remain under #182 |

## Quality evidence

- The latest committed [coverage report](../../htmlcov/index.html) comes from successful
  [CI run 41335159391](https://github.com/ukma-fin-ssdm-2026/Whadio/actions/runs/41335159391)
  at `3242e59` on 2026-11-01: 92.42% combined line and branch coverage.
- The [test plan](../validation/test-plan.md#results) records the full CI suite, CPU/CUDA ASR,
  local and external notes models, worker restart recovery and performance measurements.
- The current [static-analysis report](static-analysis.md) contains fresh raw Bandit and
  `npm audit` output and documents the remaining dependency advisory.

## Next steps

1. Publish the midterm demo (#192), then add its link beside the local run instructions.
2. Complete the public CPU deployment, timing run and automated rollback in #182.
3. Add TC-PIPE-01, TC-PIPE-02 and TC-NFR-01 to CI so recovery is no longer evidenced only by a
   manual system run.
4. Add the missing SPA flows, starting with invitations and registration, then meeting access and
   the administrator dashboard.
5. Resolve the transitive `minimatch` advisory without taking the breaking generator downgrade
   proposed by `npm audit`.

## AI Usage

The original document was drafted with Claude Code (Claude Opus 5.5). OpenAI Codex updated the
2026-11-01 status from the repository, generated OpenAPI specification, CI coverage artifact and
test-plan evidence. The changes require author review through a pull request.
