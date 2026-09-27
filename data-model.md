# Whadio Data Model

This document describes the Whadio ER data model. The PlantUML diagram is stored in [`uml/whadio-er.puml`](uml/whadio-er.puml).

The model covers the data required for the following key project functions:

1. Recording or uploading a meeting and processing it into a transcript.
2. Speaker labeling and correction.
3. Workspace glossary management.
4. Notes generation with fixed presets and optional BYOK LLM providers.
5. Workspaces, folders, roles, and restricted meeting access.
6. Transcript editing with original provenance retained.
7. External read-only sharing, export, MCP access keys, recording retention, and processing monitoring.

## Notation

- `PK` means primary key.
- `FK` means foreign key.
- `P` marks personal data.
- `S` marks sensitive, confidential, or secret data.
- Fields marked as both `P/S` may contain either personal data, confidential meeting content, or both.

## Core Entities

| Entity | Primary key | Purpose | Personal or sensitive data |
| --- | --- | --- | --- |
| `USER` | `user_id` | Registered account that can create workspaces, meetings, exports, shares, and MCP keys. | `email`, `name` are personal. `password_hash` is sensitive. |
| `WORKSPACE` | `workspace_id` | Collaboration boundary for members, folders, glossary terms, meetings, and LLM configuration. | Usually not personal, but the workspace name may reveal an organization or project. |
| `WORKSPACE_MEMBERSHIP` | `workspace_membership_id` | Connects users to workspaces and stores their cumulative role: `Member`, `Moderator`, or `Owner`. | Membership and role data can be sensitive organizational metadata. |
| `FOLDER` | `folder_id` | Organizes meetings inside a workspace. Folders do not define permissions. | Folder names may reveal topics or projects. |
| `MEETING` | `meeting_id` | Meeting metadata, generated-name state, source type, recording completeness, recording location, retention state, and access mode. | `title`, `storage_path`, timestamps, and duration can be sensitive; the recording path points to highly sensitive audio. |
| `MEETING_ACCESS_GRANT` | `access_grant_id` | Explicit access list used when a meeting is restricted to selected workspace members. | Reveals who can access a specific meeting. |
| `EXTERNAL_SHARE` | `share_id` | Read-only signed-in sharing outside the workspace, with revocation and optional speaker-name redaction. | `token_hash` is sensitive. Share metadata reveals external disclosure. |
| `TRANSCRIPT` | `transcript_id` | Transcript container for one meeting, including language, recognition model, and current revision. | Transcript metadata may be sensitive. |
| `TRANSCRIPT_REVISION` | `revision_id` | Preserves the original transcript and all edited versions. | Edit history and editor identity may be sensitive. |
| `SPEAKER` | `speaker_id` | Speaker labels for a meeting. | `display_name` and `original_display_name` are personal data. |
| `TRANSCRIPT_SEGMENT` | `segment_id` | Time-coded transcript text linked to a transcript revision and optional speaker. | `text` can contain personal data, confidential topics, or secrets. |
| `GLOSSARY_TERM` | `term_id` | Workspace-specific terms and preferred spellings used to improve recognition. | Terms, names, and descriptions may contain personal or confidential information. |
| `NOTE` | `note_id` | Generated meeting notes for a fixed preset. | `content` may contain personal data and confidential meeting decisions. |
| `LLM_PROVIDER_CONFIG` | `provider_config_id` | Workspace BYOK configuration for external LLM providers. | `api_key_encrypted` is secret credential material. |
| `MCP_KEY` | `mcp_key_id` | Personal access key for MCP clients. | `key_hash` is sensitive authentication material. |
| `EXPORT_JOB` | `export_job_id` | Tracks Markdown and VTT exports requested by users. | `storage_path` may point to sensitive exported content. |
| `PROCESSING_JOB` | `processing_job_id` | Tracks transcription, diarization, and notes jobs for monitoring. | Failure reasons can include sensitive operational or content-derived details. |

## Relationships and Cardinality

- One `USER` can own many `WORKSPACE` records.
- One `USER` can have many `WORKSPACE_MEMBERSHIP` rows; one `WORKSPACE` can have many members.
- One `WORKSPACE` contains many `FOLDER` records and many `MEETING` records.
- One `FOLDER` contains many meetings; each meeting belongs to exactly one folder.
- One `USER` can create many meetings; each meeting has one creator.
- One unrestricted meeting is available to all workspace members. A restricted meeting has one or more `MEETING_ACCESS_GRANT` rows.
- One `MEETING` can have many `EXTERNAL_SHARE` rows, each created by one user and revocable independently.
- One `MEETING` has zero or one `TRANSCRIPT`; one transcript has one or more `TRANSCRIPT_REVISION` rows.
- One `TRANSCRIPT_REVISION` has many `TRANSCRIPT_SEGMENT` rows.
- One `MEETING` has many `SPEAKER` rows; each segment may reference one speaker.
- One `WORKSPACE` has many `GLOSSARY_TERM` rows.
- One `MEETING` can produce many `NOTE` rows, for example from different presets or regenerations.
- One `WORKSPACE` has zero or one active `LLM_PROVIDER_CONFIG`.
- One `USER` can create many `MCP_KEY` rows.
- One `MEETING` can have many `EXPORT_JOB` and `PROCESSING_JOB` rows.

## Integrity Rules

- Every entity has a UUID primary key.
- `MEETING.name_is_generated` is `true` when the title was proposed by the system and the SPA should prompt the user to confirm or rename it; it becomes `false` after the user provides a title.
- `MEETING.recording_status = partial` means the capture ended without a complete stop event, for example after a lost connection or closed tab, but already acknowledged chunks were stored. Partial recordings must be shown as partial and must not be treated as complete meeting records.
- A workspace must always have exactly one owner account referenced by `owner_id`; this owner must also have an `Owner` membership in the same workspace.
- Workspace roles are cumulative: `Owner` includes `Moderator` permissions, and `Moderator` includes `Member` permissions.
- Folders do not grant or restrict access. Meeting access is determined only by workspace membership plus the meeting's `access_mode`.
- If `MEETING.access_mode = workspace`, all workspace members can access the meeting.
- If `MEETING.access_mode = restricted`, only users listed in `MEETING_ACCESS_GRANT` can access the meeting.
- A restricted meeting must not be used as cross-meeting context for another meeting's notes.
- External shares are read-only, require a signed-in recipient, can be revoked, and must store only `token_hash`, never a raw share token.
- If an external share has `redact_speaker_names = true`, it must not include the meeting recording.
- A transcript's first revision must have `revision_type = original`.
- The original transcript revision must be retained permanently. Edited revisions must not overwrite it.
- `TRANSCRIPT.current_revision_id` must point to a revision belonging to the same transcript.
- Segment time intervals must satisfy `start_time_seconds < end_time_seconds`.
- Recording files are deleted after the retention date stored in `recording_delete_after`; transcripts and notes remain after `recording_deleted_at` is set.
- LLM provider API keys and MCP keys must never be stored in plaintext.

## Personal and Sensitive Data Starting Points for Threat Analysis

The highest-risk data stores are:

- Meeting recordings referenced by `MEETING.storage_path`.
- Transcript text in `TRANSCRIPT_SEGMENT.text`.
- Speaker names in `SPEAKER.display_name` and `SPEAKER.original_display_name`.
- Generated notes in `NOTE.content`.
- Glossary terms when they contain names, internal terminology, or project details.
- LLM provider credentials in `LLM_PROVIDER_CONFIG.api_key_encrypted`.
- MCP credentials in `MCP_KEY.key_hash`.
- External share tokens represented by `EXTERNAL_SHARE.token_hash`.
- Exported files referenced by `EXPORT_JOB.storage_path`.

These fields should drive the next threat-analysis step, especially for access control, logging, export handling, retention, encryption, and external provider use.

## AI Usage

This document and the accompanying data model diagram was prepared with the assistance of Codex (GPT-5.5) and discussed in the working session of 2026-09-26. Reviewed by the author and the team before commiting.