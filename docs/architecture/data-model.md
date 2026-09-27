# Whadio Data Model

This document describes the Whadio ER data model.

![ER model](uml/er-model.svg)

Source: [uml/er-model.puml](uml/er-model.puml)

The model covers the data required for these key project functions:

1. Recording, upload and processing: `US-003`, `US-004`, `US-009`.
2. Speaker labeling and correction: `US-005`.
3. Notes generation, folder-scoped context and BYOK provider configuration: `US-006`, `US-007`, `US-008`, `US-010`.
4. Workspaces, folders, roles and restricted meeting access: `US-002`, `US-013`, `US-014`, `US-015`.
5. Transcript editing with original provenance retained: `US-011`.
6. Workspace glossary management: `US-012`.
7. External sharing, export and MCP access: `US-016`, `US-017`, `US-018`.

## Notation

- `PK` means primary key.
- `FK` means foreign key.
- `P` marks personal data.
- `S` marks sensitive, confidential, or secret data.
- Fields marked as both `P/S` may contain either personal data, confidential meeting content, or both.

## Core Entities

| Entity | Primary key | Purpose | Personal or sensitive data |
| --- | --- | --- | --- |
| `USER` | `user_id` | Registered account that can create workspaces, meetings, exports, shares, and MCP keys; `is_administrator` marks system administrators. | `email`, `name` are personal. `password_hash` is sensitive. |
| `WORKSPACE` | `workspace_id` | Collaboration boundary for members, folders, glossary terms, meetings, the default notes template, and LLM configuration. `is_personal` marks the personal workspace created during registration. | Usually not personal, but the workspace name may reveal an organization or project. |
| `WORKSPACE_MEMBERSHIP` | `workspace_membership_id` | Connects users to workspaces and stores their cumulative role: `Member`, `Moderator`, or `Owner`. | Membership and role data can be sensitive organizational metadata. |
| `INVITATION` | `invitation_id` | Pending, accepted, or declined workspace invitation for an email address with a chosen role. | `invited_email` is personal data. Invitation metadata can reveal team membership. |
| `FOLDER` | `folder_id` | Organizes meetings inside a workspace. Folders do not define permissions. | Folder names may reveal topics or projects. |
| `MEETING` | `meeting_id` | Meeting metadata, generated-name state, source type, recording completeness, meeting-level processing state, consent confirmation, recording location, retention state, and access mode. | `name`, `storage_path`, timestamps, duration, and consent-confirmation metadata can be sensitive; the recording path points to highly sensitive audio. |
| `CAPTURE_SESSION` | `capture_session_id` | Browser recording session used by the extension for chunked upload, idle-timeout recovery, and partial recording assembly. | Links a user to a recording action and may reveal meeting timing. |
| `CAPTURE_CHUNK` | `capture_chunk_id` | Acknowledged uploaded audio chunk with sequence number, object-storage key, and speaker events observed by the extension. | `storage_key` references audio chunks containing personal voice data and sensitive meeting content. `speaker_events` may contain participant names and active-speaker timing. |
| `MEETING_ACCESS_GRANT` | `access_grant_id` | Explicit access list used when a meeting is restricted to selected workspace members. | Reveals who can access a specific meeting. |
| `EXTERNAL_SHARE` | `share_id` | Read-only signed-in sharing outside the workspace, bound to the one account its creator approves, with revocation and optional speaker-name redaction. | `token_hash` is sensitive. `recipient_user_id` is personal data. Share metadata reveals external disclosure. |
| `SHARE_ACCESS_REQUEST` | `share_access_request_id` | Request to read a shared meeting, created when a signed-in account opens the share link; the share's creator approves or declines it. | `requester_user_id` is personal data: it links a person outside the workspace to a meeting they tried to open. |
| `TRANSCRIPT` | `transcript_id` | Transcript container for one meeting, including language, recognition model, and current revision. | Transcript metadata may be sensitive. |
| `TRANSCRIPT_REVISION` | `revision_id` | Preserves the original transcript and all edited versions. | Edit history and editor identity may be sensitive. |
| `SPEAKER` | `speaker_id` | Speaker labels stored per transcript revision, so speaker renames preserve the original labels and create edited revisions. | `display_name` is personal data. |
| `TRANSCRIPT_SEGMENT` | `segment_id` | Time-coded transcript text linked to a transcript revision and optional speaker. | `text` can contain personal data, confidential topics, or secrets. |
| `GLOSSARY_TERM` | `term_id` | Workspace-specific terms and preferred spellings used to improve recognition. | Terms, names, and descriptions may contain personal or confidential information. |
| `NOTE` | `note_id` | Generated meeting notes for a fixed preset. | `content` may contain personal data and confidential meeting decisions. |
| `NOTE_CONTEXT_MEETING` | `note_context_meeting_id` | Records the meetings used as context for a generated note, including a name snapshot so notes remain understandable after a context meeting is deleted. | `context_meeting_name_snapshot` can reveal sensitive meeting topics. |
| `LLM_PROVIDER_CONFIG` | `provider_config_id` | Workspace notes-provider configuration, either built-in `Whadio` or an external BYOK provider. | `api_key_encrypted` is secret credential material when an external provider is used. |
| `MCP_KEY` | `mcp_key_id` | Personal access key for MCP clients. | `key_hash` is sensitive authentication material. |
| `PROCESSING_JOB` | `processing_job_id` | Tracks transcription and notes jobs for monitoring. Diarization is part of the transcription job. | Failure reasons can include sensitive operational or content-derived details. |

## Relationships and Cardinality

- One `USER` has one or more `WORKSPACE_MEMBERSHIP` rows because registration creates a personal workspace.
- One `WORKSPACE` has one or more `WORKSPACE_MEMBERSHIP` rows because every workspace has an Owner.
- Every `WORKSPACE` has exactly one `WORKSPACE_MEMBERSHIP` row with `role = Owner`.
- One `WORKSPACE` contains one or more `FOLDER` records because every workspace has a default folder.
- One `WORKSPACE` can have many `INVITATION` rows.
- One `FOLDER` contains many meetings; each meeting belongs to exactly one folder.
- One `USER` can create many meetings; each meeting has one creator.
- One extension-recorded `MEETING` has zero or one `CAPTURE_SESSION`; uploaded meetings have none.
- One `CAPTURE_SESSION` has many `CAPTURE_CHUNK` rows.
- One unrestricted meeting is available to all workspace members. A restricted meeting must have one or more `MEETING_ACCESS_GRANT` rows.
- One `MEETING` can have many `EXTERNAL_SHARE` rows, each created by one user and revocable independently.
- One `EXTERNAL_SHARE` is bound to zero or one recipient `USER`, set when its creator approves a request.
- One `EXTERNAL_SHARE` has many `SHARE_ACCESS_REQUEST` rows; each request is made by one `USER`.
- One `MEETING` has zero or one `TRANSCRIPT`; one transcript has one or more `TRANSCRIPT_REVISION` rows.
- One `TRANSCRIPT_REVISION` has many `TRANSCRIPT_SEGMENT` rows.
- One `TRANSCRIPT_REVISION` has many `SPEAKER` rows; each segment may reference one speaker label from the same revision.
- One `WORKSPACE` has many `GLOSSARY_TERM` rows.
- One `MEETING` can produce many `NOTE` rows, for example from different presets or regenerations.
- One `NOTE` can reference many context meetings through `NOTE_CONTEXT_MEETING`.
- One `WORKSPACE` has zero or one active `LLM_PROVIDER_CONFIG`.
- One `USER` can create many `MCP_KEY` rows.
- One `MEETING` can have many `PROCESSING_JOB` rows.

## Integrity Rules

- Every entity has a UUID primary key.
- `MEETING.name_is_generated` is `true` when the meeting name was proposed by the system and the SPA should prompt the user to confirm or rename it; it becomes `false` after the user provides a name.
- `MEETING.storage_path` and `MEETING.duration_seconds` are optional while an extension recording is still being captured and before chunks have been assembled.
- `MEETING.recording_status = partial` means the capture ended without a complete stop event, for example after a lost connection or closed tab, but already acknowledged chunks were stored. Partial recordings must be shown as partial and must not be treated as complete meeting records.
- `MEETING.processing_state` is the meeting-level state shown in the SPA: `recording`, `queued`, `processing`, `processed`, or `failed`.
- `MEETING.consent_confirmed_at` and `MEETING.consent_confirmed_by_user_id` are optional because extension recordings require consent confirmation, while uploaded recordings do not have the extension consent step.
- `CAPTURE_SESSION.last_chunk_seq` and `CAPTURE_SESSION.last_chunk_at` are optional until the first chunk arrives; after that, they let the scheduler find captures that have been idle past the timeout.
- `CAPTURE_CHUNK` must be unique by `(capture_session_id, seq)`, so chunk upload retries are idempotent.
- A workspace must always have exactly one membership with `role = Owner`.
- `WORKSPACE_MEMBERSHIP` must be unique by `(workspace_id, user_id)`, so one user has at most one role in a workspace.
- `INVITATION.role` is limited to `Member` or `Moderator`; invitations cannot grant `Owner`.
- `GLOSSARY_TERM` must be unique by `(workspace_id, term)`, because duplicate glossary terms are rejected.
- `GLOSSARY_TERM.source_meeting_id` is optional and records the meeting where a transcript correction produced the term.
- Workspace roles are cumulative: `Owner` includes `Moderator` permissions, and `Moderator` includes `Member` permissions.
- Folders do not grant or restrict access. Meeting access is determined by workspace membership plus the meeting's `access_mode`, and for people outside the workspace, an active `EXTERNAL_SHARE` bound to them.
- If `MEETING.access_mode = workspace`, all workspace members can access the meeting.
- If `MEETING.access_mode = restricted`, only users listed in `MEETING_ACCESS_GRANT` can access the meeting.
- A restricted meeting must not be used as cross-meeting context for another meeting's notes.
- External shares are read-only, require a signed-in recipient, can be revoked, and must store only `token_hash`, never a raw share token.
- An external share grants access only to its `recipient_user_id`. While it is null, opening the link only creates a `SHARE_ACCESS_REQUEST`; approving a request sets `recipient_user_id` to the requester.
- Only the share's creator (`EXTERNAL_SHARE.created_by_user_id`) approves or declines its requests. Once `recipient_user_id` is set, further requests can only be declined.
- `SHARE_ACCESS_REQUEST` must be unique by `(share_id, requester_user_id)`, so an account cannot repeat a declined request.
- If an external share has `redact_speaker_names = true`, it must not include the meeting recording.
- A transcript's first revision must have `revision_type = original`.
- The original transcript revision must be retained permanently. Edited transcript text or speaker-label changes create edited revisions and must not overwrite the original.
- `TRANSCRIPT.current_revision_id` must point to a revision belonging to the same transcript.
- `NOTE.created_by_user_id` is optional because first notes may be generated automatically; regenerations can store the requesting user.
- `NOTE_CONTEXT_MEETING.context_meeting_id` is optional so the note can remain unchanged after a context meeting is deleted; `context_meeting_name_snapshot` preserves what was shown to readers.
- `LLM_PROVIDER_CONFIG.api_key_encrypted` is required unless `provider = Whadio`.
- `PROCESSING_JOB.created_at` stores when the job was queued, and `attempts` stores retry count for monitoring and retry limits.
- Segment time intervals must satisfy `start_time_seconds < end_time_seconds`.
- Recording files are deleted after the retention date stored in `recording_delete_after`; transcripts and notes remain after `recording_deleted_at` is set.
- LLM provider API keys and MCP keys must never be stored in plaintext.

## Personal and Sensitive Data Starting Points for Threat Analysis

The highest-risk data stores are:

- Meeting recordings referenced by `MEETING.storage_path`; the object itself contains personal voice data.
- Meeting names in `MEETING.name`, especially generated names based on transcripts.
- Consent confirmation metadata in `MEETING.consent_confirmed_at` and `MEETING.consent_confirmed_by_user_id`.
- Capture chunks referenced by `CAPTURE_CHUNK.storage_key`.
- Speaker events in `CAPTURE_CHUNK.speaker_events`.
- Transcript text in `TRANSCRIPT_SEGMENT.text`.
- Speaker names in `SPEAKER.display_name`.
- Generated notes in `NOTE.content`.
- Note context meeting snapshots in `NOTE_CONTEXT_MEETING.context_meeting_name_snapshot`.
- Glossary terms when they contain names, internal terminology, or project details.
- LLM provider credentials in `LLM_PROVIDER_CONFIG.api_key_encrypted`.
- MCP credentials in `MCP_KEY.key_hash`.
- External share tokens represented by `EXTERNAL_SHARE.token_hash`.
- Share recipients and requesters in `EXTERNAL_SHARE.recipient_user_id` and `SHARE_ACCESS_REQUEST.requester_user_id`, which reveal who outside the workspace read or tried to open a meeting.

These fields should drive the next threat-analysis step, especially for access control, logging, export handling, retention, encryption, and external provider use.

## AI Usage

This document and the accompanying data model diagram were prepared with the assistance of Codex (GPT-5.5) and discussed in the working session of 2026-09-26. Reviewed by the author and the team before committing.
