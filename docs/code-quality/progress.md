# Implementation Progress

State on 2026-10-12, and the plan for the minimal working prototype due by Lab 6.

## The MVP

The prototype covers the core path, from a recording to its notes:

1. A user signs in and uploads a recorded meeting (any audio or video file, for example one
   recorded with OBS) to a workspace.
2. The recording goes to object storage (SeaweedFS), and Processing queues a transcription job on
   RabbitMQ.
3. The ASR worker transcribes the recording with speaker separation and returns the transcript.
4. Processing stores the transcript and queues a notes job; the notes worker writes the notes
   through an LLM API.
5. The user reads the transcript and the notes in the web app.

Along the way, Access Policy decides who may open a meeting, Audit records who changed or deleted
what, and Retention deletes recordings 90 days after the meeting.

Left for later labs:

- live capture through the Chrome extension;
- e-mail notifications, since SMTP is a paid service;
- administrator monitoring, planned for the observability lab;
- a self-hosted LLM, which needs a shared GPU host;
- issuing personal MCP keys; the read-only MCP server already checks them.

## Status

| Component | Owner | Status | What exists |
|---|---|---|---|
| Tooling and CI | Andrii | Done | Pre-commit hooks, CI, the dependency audit and Dependabot ([static analysis](static-analysis.md)) |
| Database | Valeriia | Done | The schema split by owning module, six Alembic migrations, separate owner and application roles, and integrity guards: one Owner and one default folder per workspace, a sealed original transcript, an append-only audit log ([database](../architecture/database.md)) |
| Job contracts, broker, object storage | Andrii | Done | Typed job and result messages between Processing and the workers, RabbitMQ helpers, S3 storage with presigned links |
| Transcription worker | Andrii | Done | Whisper or Parakeet recognition, pyannote speaker diarization and language detection, on a CPU or a GPU, in parallel slots under a supervisor that stops the worker when it can no longer take jobs |
| Notes worker | Andrii | Done | Notes written by Claude through the Anthropic API, with presets and a context budget |
| Accounts & Workspaces | Denys | Done | Sign-in with argon2id password hashes, browser and extension sessions, workspaces and their members |
| Processing, Audit | Denys | Done | Processing queues the jobs and stores the workers' results, accepting each result only from the worker that may send it; Audit records changes in the same transaction |
| Meetings, Access Policy | Valeriia | Done | Upload, folders, transcripts, notes and their Markdown and VTT export; access checks, share links and access requests |
| Retention | Valeriia | Done | A scheduler job that deletes recordings once they expire |
| Web SPA | Zlata | In progress | The workspace list, meeting library, upload and settings screens, on mock data; not connected to the API yet |

The backend runs the whole path: an upload is stored in SeaweedFS and queued for transcription,
and the web app stores the workers' results as they arrive.

## The working component

The transcription and notes workers run end to end on their own: they take jobs from RabbitMQ,
read the recording from SeaweedFS, and publish their results for Processing.
`uv run task workers:up` starts them in Docker Compose; the README lists the keys they need.

They meet the standards of the [code quality policy](../../TeamCharter.md#11-code-quality-and-review-policy):
every commit-hook check passes, and 131 tests cover them, 10 of them slow tests that run real
models or the Compose services.

## Next steps to Lab 6

1. Let the first account be created: there is no registration route or command yet, so nobody
   can sign in to a fresh deployment.
2. Connect the web SPA to the API: sign-in, workspaces, upload, the meeting list, the transcript
   and the notes.
3. Run the whole path end to end in Docker Compose, from an uploaded recording to its notes in
   the browser.
4. Add a linter, a formatter and `npm audit` for the frontend.

## AI Usage

Drafted with Claude Code (Claude Opus 5.5) from the repository's state and the team's MVP
decisions; checked and edited by Andrii Shalaiev, and reviewed through a pull request before
merging.
