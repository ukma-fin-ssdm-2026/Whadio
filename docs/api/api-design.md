# API Design

This document describes Whadio's HTTP API: what it exposes, how its resources are modelled,
what each error means, and the decisions behind its conventions. It covers the **whole designed
API**. The code in [`src/api/`](../../src/api/) implements one vertical slice of it as stubs
(section 2).

The API is written code-first: FastAPI builds the OpenAPI specification from the code, and
nothing in it is written by hand. The generated specification is committed as
[`openapi-generated.yaml`](openapi-generated.yaml) and
[`openapi-generated.json`](openapi-generated.json), and published through
[`index.html`](index.html). The architecture this API serves is described in the
[high-level design](../architecture/high-level-design.md).

## 1. Architecture overview

- **Base URL:** `http://localhost:3000/api/v1` in development. `/health` and the MCP endpoint
  `/mcp/` sit outside the version prefix.
- **Style:** REST over HTTPS. Bodies are JSON; audio is sent as `multipart/form-data`.
- **Interactive docs:** Swagger UI at `/api-docs`, ReDoc at `/redoc`, the live specification at
  `/openapi.json`, and the committed generated specification in this directory.
- **Authentication:**
  - the web app uses a browser session cookie;
  - the Chrome extension uses a bearer token that only the Capture API accepts;
  - AI assistants use a personal MCP key on the MCP endpoint only.
- **Errors:** one envelope for every 4xx and 5xx response (section 5).
- **Versioning:** the major version is in the path (section 6.10).
- **Runtime:** the `web` unit of the [modular monolith](../architecture/decisions/ADR-001.md).

The three HTTP interfaces of the high-level design map onto the API as follows:

- **Web API:** everything under `/api/v1` except `/captures/*`. The web SPA uses it.
- **Capture API:** `/api/v1/captures/*` and the recording upload. The Chrome extension and the
  SPA use it.
- **MCP:** `/mcp/`. The user's AI assistant uses it.

The code follows the module boundaries of the high-level design: `accounts`, `meetings`,
`access_policy`, `processing`, `export`, `capture` and `admin`. Each module serves its own
resources, so there is no separate "Web API" layer.

## 2. Implementation status

The design has **70 operations**. The code implements **16 of them as stubs**:

- **Sessions:** sign in and sign out.
- **Workspaces:** list, create, read, update, delete.
- **Meetings:** list with filters, upload a recording, read, rename or move, delete.
- **Transcript:** read the current revision.
- **Notes:** list them, regenerate them.
- **Health:** liveness.

Every other operation in section 4 is **designed**: its contract is fixed here, and it is not
yet in the code. Each operation in section 4 is marked *Stub* or *Designed*.

**What a stub does:**
- It answers with fixed demo data, listed at the top of the Swagger page. Writes return the
  result they would have, but store nothing.
- It validates all input for real: types, lengths, enums, unknown fields and cross-field rules.
- It authenticates for real against one demo account: a missing or unknown session gets `401`.
- It returns errors that follow from the demo data:
  - `404` for an id that does not exist;
  - `409 PERSONAL_WORKSPACE` for deleting the personal workspace;
  - `409 NOT_TRANSCRIBED` for the transcript of a queued meeting;
  - `422` for a `folder_id` that is not a folder of the meeting's workspace;
  - `413` and `415` for an upload that is too large or is not audio.

**What a stub documents but never produces:**
- role checks (`403 INSUFFICIENT_ROLE`);
- limits (`429`, `409 REGENERATION_LIMIT`, `409 NOTES_IN_PROGRESS`);
- the origin check (`403 ORIGIN_REJECTED`) and `Idempotency-Key` replays (section 6.8);
- the `X-Request-ID` header on successful responses: the stub sets it on errors only;
- MCP key authentication (section 6.11).

## 3. Resource model

Resources are plural nouns, nested at most one level under their owner
(`/workspaces/{workspace_id}/…`). A resource with its own identity is then addressed directly,
as in `/meetings/{meeting_id}` and `/shares/{share_id}`. An action that is not CRUD is a
sub-resource, such as `…/cancel`, `…/complete` or `…/approve`.

### User

- **Endpoint:** `/users/me`
- **Module:** Accounts & Workspaces
- **Description:** a person with an account. The email address is proven before the account
  exists.
- **Attributes:**
  - `id` (uuid)
  - `email` (string): the proven address
  - `name` (string)
  - `is_administrator` (bool): opens the admin dashboard
  - `created_at` (datetime)
- **Relations:** has one personal workspace; is a member of workspaces; owns MCP keys.

### Session

- **Endpoint:** `/sessions`
- **Module:** Accounts & Workspaces
- **Description:** a signed-in browser or extension. Only a hash of its token is stored.
- **Attributes:**
  - `kind` (enum): `browser` | `extension`
  - `expires_at` (datetime): fixed at creation; 14 days for `browser`, 24 hours for
    `extension`
- **Relations:** belongs to a user.

### Workspace

- **Endpoint:** `/workspaces`
- **Module:** Accounts & Workspaces
- **Description:** the unit of membership and the boundary of every meeting.
- **Attributes:**
  - `id` (uuid)
  - `name` (string, 1–100)
  - `is_personal` (bool): created with the account; it cannot be deleted and takes no
    invitations
  - `my_role` (enum): `member` | `moderator` | `owner`, the caller's role
  - `member_count` (int)
  - `default_preset` (enum): `summary` | `detailed` | `interview`
  - `notes_provider` (enum): `whadio` | `anthropic` | `openai` | `google`
- **Relations:** has members, invitations, folders, glossary terms and meetings; has at most
  one notes provider configuration.

### Member and invitation

- **Endpoints:** `/workspaces/{workspace_id}/members`, `/workspaces/{workspace_id}/invitations`,
  `/invitations/{invitation_id}`
- **Module:** Accounts & Workspaces
- **Description:** a user's role in a workspace, and a pending offer of one.
- **Attributes:**
  - member: `user_id`, `name`, `email`, `role`, `joined_at`
  - invitation: `id`, `email`, `role` (`member` | `moderator`), `status`
    (`pending` | `accepted` | `declined` | `cancelled`), `expires_at` (7 days),
    `link_active`
- **Relations:** an invitation belongs to a workspace and to the Moderator who created it.

### Folder and glossary term

- **Endpoints:** `/workspaces/{workspace_id}/folders`,
  `/workspaces/{workspace_id}/glossary-terms`
- **Module:** Meetings
- **Description:** a folder files meetings and is the context set for notes. A glossary term
  is supplied to speech recognition for the workspace.
- **Attributes:**
  - folder: `id`, `name` (1–100, unique per workspace ignoring case), `is_default`,
    `meeting_count`
  - term: `id`, `term`, `preferred_form`, `description`, `source_meeting_id`,
    `created_by_user_id`
- **Relations:** both belong to a workspace; a folder holds meetings.

### Meeting

- **Endpoints:** `/workspaces/{workspace_id}/meetings`, `/meetings/{meeting_id}`
- **Module:** Meetings
- **Description:** one recorded or uploaded conversation and its processing state.
- **Attributes:**
  - `id`, `workspace_id`, `folder_id` (uuid)
  - `name` (string, 1–200) and `name_is_generated` (bool)
  - `recorded_at` (datetime): not editable
  - `processing_state` (enum): `recording` | `queued` | `processing` | `processed` | `failed`
  - `recording_status` (enum): `complete` | `partial`
  - `source_type` (enum): `extension` | `upload`
  - `access_mode` (enum): `workspace` | `restricted`
  - `failure_reason` (string or null): never contains meeting content
  - `recording_delete_after` (datetime): the retention deadline
- **Relations:** in one folder; has a recording, a transcript, notes, an access setting and
  shares.

### Transcript

- **Endpoint:** `/meetings/{meeting_id}/transcript`
- **Module:** Meetings
- **Description:** the recognised text, kept as revisions. The original revision is never
  changed.
- **Attributes:**
  - `language`, `model_name` (string)
  - `revision`: `id`, `revision_type` (`original` | `edited`), `is_current`
  - `original_revision_id` (uuid)
  - `speakers`: `id`, `display_name`, `is_unnamed`
  - `segments`: `id`, `speaker_id`, `start_seconds`, `end_seconds`, `text`
- **Relations:** belongs to a meeting; each edit creates a revision.

### Notes and processing job

- **Endpoint:** `/meetings/{meeting_id}/notes`
- **Module:** Processing
- **Description:** generated notes, kept in versions, and the job that produces them.
- **Attributes:**
  - notes: `id`, `preset`, `provider`, `model_name`, `content` (Markdown), `is_current`,
    `context_meetings`
  - job: `id`, `kind` (`transcription` | `notes`), `status`
    (`queued` | `running` | `succeeded` | `failed`)
- **Relations:** notes belong to a meeting and name the meetings of its folder that served as
  context.

### Share and access request

- **Endpoints:** `/meetings/{meeting_id}/shares`, `/shares/{share_id}`,
  `/share-access-requests/{request_id}`
- **Module:** Access Policy
- **Description:** a link to a meeting for someone outside the workspace. It grants nothing
  until its creator approves one account's request.
- **Attributes:**
  - share: `id`, `redact_speaker_names`, `recipient_user_id`, `revoked_at`
  - request: `id`, requester's `name` and `email`, `status`
- **Relations:** a share belongs to a meeting and its creator; it has access requests and
  binds to at most one account.

### Capture

- **Endpoint:** `/captures`
- **Module:** Capture
- **Description:** a recording in progress from the extension, uploaded in numbered chunks.
- **Attributes:**
  - `id`
  - `status` (enum): `recording` | `idle` | `assembled` | `abandoned`
  - `received_seqs` (int list)
  - `max_chunk_bytes`
- **Relations:** creates a meeting and holds its chunks until they are assembled.

### MCP key

- **Endpoint:** `/users/me/mcp-keys`
- **Module:** Accounts & Workspaces
- **Description:** a personal key for an AI assistant. It is shown once and stored hashed.
- **Attributes:** `id`, `created_at`, `expires_at`, `revoked_at`, `is_active`
- **Relations:** belongs to a user, and reads only what that user can read.

## 4. Endpoints

Paths are relative to `/api/v1` unless they start with `/health`. Each operation lists:
- **Caller:** who may call it. *Public* needs no session; every other operation needs one.
- **Success:** the status code and what the response carries.
- **Rules:** the behaviour a client must know about.
- **Errors:** the errors specific to this operation. The common errors of section 5.3, such as
  `401`, `422` and `400`, apply on top and are not repeated.

### 4.1 Accounts, sessions and keys

#### `GET /instance` · Describe this instance

- **Status:** Designed · **Caller:** public · **Success:** `200`, the registration mode and
  the API version
- **Rules:** tells the web app whether to offer registration and password reset.
- **Errors:** none.

#### `POST /registrations` · Request a registration link

- **Status:** Designed · **Caller:** public · **Success:** `202`, a fixed confirmation
- **Rules:**
  - Emails a single-use link valid for 24 hours. The account is created only when the link is
    used (FR-001).
  - The response is identical in every case, so it reveals nothing about the address:
    - a new address gets a registration link;
    - an address that already has an account gets a sign-in reminder with a password-reset
      link;
    - a repeat within 20 minutes changes nothing, and the earlier link keeps working.
- **Errors:**
  - `403 INVITE_ONLY_INSTANCE`: the operator runs the instance invite-only.

#### `POST /registrations/{registration_id}/complete` · Create the account from a link

- **Status:** Designed · **Caller:** public · **Success:** `201`, the new user; the session
  cookie is set
- **Rules:**
  - Works in both modes, because operator-issued links work on invite-only instances.
  - Creates the account, its personal workspace and default folder, and signs the browser in.
  - Requires `accept_terms: true` (FR-002) and a password of 12 to 128 characters.
- **Errors:**
  - `404 LINK_INVALID`: the link cannot be used (section 6.3).

#### `POST /password-resets` · Request a password-reset link

- **Status:** Designed · **Caller:** public · **Success:** `202`, a fixed confirmation
- **Rules:**
  - Emails a single-use link valid for 1 hour (FR-048).
  - The response is the same whether or not the address has an account. An unknown address
    receives nothing.
  - A repeat within 20 minutes changes nothing.
- **Errors:**
  - `403 INVITE_ONLY_INSTANCE`: the operator runs the instance invite-only.

#### `POST /password-resets/{reset_id}/complete` · Set a new password from a link

- **Status:** Designed · **Caller:** public · **Success:** `204`
- **Rules:** ends every session and extension token of the account, this browser's included.
  MCP keys keep working.
- **Errors:**
  - `404 LINK_INVALID`: the link cannot be used (section 6.3).

#### `POST /sessions` · Sign in

- **Status:** Stub · **Caller:** public · **Success:** `201`, the session and its user
- **Rules:**
  - `kind: browser`, the default, sets an `HttpOnly`, `Secure`, `SameSite=Strict` cookie valid
    for 14 days.
  - `kind: extension` returns a bearer token instead. It is shown once and valid for 24 hours.
  - Neither is extended by use (FR-003).
- **Errors:**
  - `401 INVALID_CREDENTIALS`: unknown address or wrong password. The error never says which,
    so it cannot be used to find accounts.
  - `429 RATE_LIMITED`: too many attempts from this IP address.

#### `DELETE /sessions/current` · Sign out

- **Status:** Stub · **Caller:** anyone · **Success:** `204`
- **Rules:** ends the session presented by the cookie or the bearer token, and clears the
  cookie. It answers `204` even without a session, because signing out is idempotent.
- **Errors:** none.

#### `GET /users/me` · Get the signed-in user

- **Status:** Designed · **Caller:** any user · **Success:** `200`, the user
- **Errors:** common only.

#### `GET /users/me/mcp-keys` · List my MCP keys

- **Status:** Designed · **Caller:** any user · **Success:** `200`, a page of keys, newest
  first
- **Rules:** revoked keys are included. A key's secret is never shown again after creation.
- **Errors:** common only.

#### `POST /users/me/mcp-keys` · Create an MCP key

- **Status:** Designed · **Caller:** any user · **Success:** `201`, the key with its secret
- **Rules:** the secret is shown once and only its hash is stored (FR-043).
  `expires_in_days` is between 1 and 365; without it, the key does not expire.
- **Errors:** common only.

#### `DELETE /users/me/mcp-keys/{key_id}` · Revoke an MCP key

- **Status:** Designed · **Caller:** the key's owner · **Success:** `204`
- **Rules:** revoking twice is harmless.
- **Errors:**
  - `404 NOT_FOUND`: no such key among the caller's own.

### 4.2 Workspaces, members and invitations

#### `GET /workspaces` · List my workspaces

- **Status:** Stub · **Caller:** any user · **Success:** `200`, a page of workspaces, oldest
  first
- **Rules:** the personal workspace is included.
- **Errors:** common only.

#### `POST /workspaces` · Create a workspace

- **Status:** Stub · **Caller:** any user · **Success:** `201`, the workspace; `Location`
  points to it
- **Rules:** the caller becomes the Owner. The workspace gets one default folder and no
  meetings (FR-005).
- **Errors:** common only.

#### `GET /workspaces/{workspace_id}` · Get a workspace

- **Status:** Stub · **Caller:** any member · **Success:** `200`, the workspace
- **Errors:**
  - `404 NOT_FOUND`: no such workspace, or the caller is not a member.

#### `PATCH /workspaces/{workspace_id}` · Update workspace settings

- **Status:** Stub · **Caller:** Owner · **Success:** `200`, the updated workspace
- **Rules:** changes `name`, `default_preset`, or both. At least one is required.
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller is a member, but not the Owner.
  - `404 NOT_FOUND`: no such workspace, or the caller is not a member.

#### `DELETE /workspaces/{workspace_id}` · Delete a workspace

- **Status:** Stub · **Caller:** Owner · **Success:** `204`
- **Rules:** deletes the folders, meetings, recordings, transcripts and notes with it
  (FR-008).
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller is a member, but not the Owner.
  - `404 NOT_FOUND`: no such workspace, or the caller is not a member.
  - `409 PERSONAL_WORKSPACE`: the personal workspace lives as long as the account.

#### `GET`, `PUT`, `DELETE /workspaces/{workspace_id}/llm-provider` · Notes provider

- **Status:** Designed · **Caller:** Owner · **Success:** `200` with the configuration (`GET`,
  `PUT`); `204` (`DELETE`)
- **Rules:**
  - `GET` never returns the API key; `has_api_key` says whether one is stored.
  - `PUT` replaces the configuration. An external provider needs a key, and `whadio` takes
    none. With an external provider, the transcripts of each notes context set are sent to
    it, and every member sees that (FR-021).
  - `DELETE` returns to the built-in model, so no request leaves the system (FR-022).
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller is a member, but not the Owner.
  - `404 NOT_FOUND`: no such workspace, or the caller is not a member.

#### `GET /workspaces/{workspace_id}/members` · List members

- **Status:** Designed · **Caller:** any member · **Success:** `200`, a page of members, by
  joining time
- **Errors:**
  - `404 NOT_FOUND`: no such workspace, or the caller is not a member.

#### `PATCH /workspaces/{workspace_id}/members/{user_id}` · Change a member's role

- **Status:** Designed · **Caller:** Moderator or Owner · **Success:** `200`, the member
- **Rules:** switches between `member` and `moderator`. The change applies from the member's
  next request (FR-007).
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller is a plain member.
  - `404 NOT_FOUND`: no such workspace or member.
  - `409 OWNER_IMMUTABLE`: the target is the Owner.

#### `DELETE /workspaces/{workspace_id}/members/{user_id}` · Remove a member

- **Status:** Designed · **Caller:** Moderator or Owner · **Success:** `204`
- **Rules:** the member loses access to the workspace and all of its meetings at once.
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller is a plain member.
  - `404 NOT_FOUND`: no such workspace or member.
  - `409 OWNER_IMMUTABLE`: the target is the Owner.

#### `GET /workspaces/{workspace_id}/invitations` · List pending invitations

- **Status:** Designed · **Caller:** Moderator or Owner · **Success:** `200`, a page of
  invitations, newest first
- **Rules:** `link_active` becomes false once the link expires, or once its creator loses the
  Moderator role.
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller is a plain member.
  - `404 NOT_FOUND`: no such workspace, or the caller is not a member.

#### `POST /workspaces/{workspace_id}/invitations` · Invite a person

- **Status:** Designed · **Caller:** Moderator or Owner · **Success:** `201` for a new
  invitation; `200` when a pending one was replaced
- **Rules:**
  - Creates a single-use link valid for 7 days (FR-006).
  - In `verified` mode the link is emailed. On an invite-only instance it is returned once in
    `link`, for the Moderator to hand over.
  - The checks run in this order, and the first failure answers:
    1. the workspace is not personal;
    2. the address does not belong to a member;
    3. the caller has invited fewer than 20 addresses today;
    4. in `verified` mode, the address was not invited to this workspace in the last day,
       counting cancelled and declined invitations;
    5. a pending invitation for the address is replaced in place: same id, and the earlier
       link stops working.
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller is a plain member.
  - `404 NOT_FOUND`: no such workspace, or the caller is not a member.
  - `409 PERSONAL_WORKSPACE`: personal workspaces take no invitations.
  - `409 ALREADY_MEMBER`: the address belongs to a member.
  - `429 INVITATION_LIMIT`: the caller reached 20 addresses today.
  - `429 INVITATION_COOLDOWN`: this address was invited to this workspace in the last day.

#### `POST /workspaces/{workspace_id}/invitations/{invitation_id}/cancel` · Cancel

- **Status:** Designed · **Caller:** Moderator or Owner · **Success:** `200`, the cancelled
  invitation
- **Rules:** the link stops working. The invitation still counts towards the one-day wait for
  its address.
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller is a plain member.
  - `404 NOT_FOUND`: no such workspace or invitation.
  - `409 INVITATION_NOT_PENDING`: already accepted, declined or cancelled.

#### `POST /invitations/{invitation_id}/preview` · Preview an invitation link

- **Status:** Designed · **Caller:** public · **Success:** `200`, the workspace, the role,
  and whether the address has an account
- **Rules:** changes nothing. It is a `POST` although it only reads (section 6.3).
- **Errors:**
  - `404 LINK_INVALID`: the link cannot be used.

#### `POST /invitations/{invitation_id}/accept` · Accept an invitation

- **Status:** Designed · **Caller:** the invited user, signed in · **Success:** `200`, the
  membership
- **Rules:** accepting again with the same account returns the same membership.
- **Errors:**
  - `403 EMAIL_MISMATCH`: the signed-in account has a different address.
  - `404 LINK_INVALID`: the link cannot be used.
  - `409 ALREADY_MEMBER`: the account is already a member.

#### `POST /invitations/{invitation_id}/register` · Create an account through an invitation

- **Status:** Designed · **Caller:** public · **Success:** `201`, the user and the
  membership; the session cookie is set
- **Rules:** for an invited address without an account. It creates the account and its
  personal workspace, joins the workspace, and signs the browser in (FR-002).
- **Errors:**
  - `404 LINK_INVALID`: the link cannot be used.
  - `409 ACCOUNT_EXISTS`: the address has an account, so sign in and accept instead.

#### `POST /invitations/{invitation_id}/decline` · Decline an invitation

- **Status:** Designed · **Caller:** public · **Success:** `200`, the declined invitation
- **Rules:** needs no account. The link stops working.
- **Errors:**
  - `404 LINK_INVALID`: the link cannot be used.

### 4.3 Folders and glossary

#### `GET`, `POST /workspaces/{workspace_id}/folders` · List or create folders

- **Status:** Designed · **Caller:** any member to list; Moderator or Owner to create ·
  **Success:** `200`, a page with the default folder first; `201`, the new folder
- **Rules:** folders are flat and only organise meetings: they never grant or restrict
  access. A folder is the context set for notes (FR-019).
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: a plain member tries to create one.
  - `404 NOT_FOUND`: no such workspace, or the caller is not a member.
  - `409 FOLDER_EXISTS`: the name is taken in this workspace, ignoring case.

#### `PATCH`, `DELETE /workspaces/{workspace_id}/folders/{folder_id}` · Rename or delete

- **Status:** Designed · **Caller:** Moderator or Owner · **Success:** `200`, the folder;
  `204` on delete
- **Rules:** deleting moves the folder's meetings to the default folder; no meeting is deleted
  (FR-034).
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller is a plain member.
  - `404 NOT_FOUND`: no such workspace or folder.
  - `409 FOLDER_EXISTS`: the new name is taken.
  - `409 DEFAULT_FOLDER`: the default folder cannot be deleted.

#### `GET`, `POST /workspaces/{workspace_id}/glossary-terms` · List or add terms

- **Status:** Designed · **Caller:** any member · **Success:** `200`, a page in alphabetical
  order; `201`, the new term
- **Rules:** later transcriptions in the workspace use the terms (FR-029).
  `source_meeting_id` records the transcript correction the term came from (FR-030).
- **Errors:**
  - `404 NOT_FOUND`: no such workspace, or the caller is not a member.
  - `409 TERM_EXISTS`: the term is already in the glossary, ignoring case.

#### `PATCH`, `DELETE /workspaces/{workspace_id}/glossary-terms/{term_id}` · Edit or remove

- **Status:** Designed · **Caller:** the term's author, a Moderator or the Owner ·
  **Success:** `200`, the term; `204` on delete
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller is a plain member who did not add the term.
  - `404 NOT_FOUND`: no such workspace or term.
  - `409 TERM_EXISTS`: the new term is already in the glossary.

### 4.4 Meetings and transcripts

#### `GET /workspaces/{workspace_id}/meetings` · List meetings

- **Status:** Stub · **Caller:** any member · **Success:** `200`, a page of meetings, newest
  recording first
- **Rules:**
  - Shows each meeting's processing state (FR-031).
  - Leaves out restricted meetings the caller was not selected for.
  - The filters combine (FR-032): `folder_id`, a part of `name`, and `recorded_from` (inclusive)
    to `recorded_to` (exclusive). `recorded_to` must be later than `recorded_from`.
  - An empty page means that nothing matched.
- **Errors:**
  - `404 NOT_FOUND`: no such workspace, or the caller is not a member.

#### `POST /workspaces/{workspace_id}/meetings` · Upload a recording

- **Status:** Stub · **Caller:** any member, with a browser session or the extension token ·
  **Success:** `201`, the meeting in state `queued`; `Location` points to it
- **Rules:**
  - Multipart: an audio `file`, plus an optional `folder_id` and `name` (FR-013).
  - The meeting is queued for processing at once. Its speakers are labelled `Speaker 1`,
    `Speaker 2`, and so on (FR-016).
  - `folder_id` must be a folder of this workspace; without it, the default folder is used.
- **Errors:**
  - `404 NOT_FOUND`: no such workspace, or the caller is not a member.
  - `413 PAYLOAD_TOO_LARGE`: the file is larger than 500 MiB.
  - `415 UNSUPPORTED_MEDIA_TYPE`: the file is not `audio/*`, so no meeting is created.

#### `GET /meetings/{meeting_id}` · Get a meeting

- **Status:** Stub · **Caller:** any member who can read it · **Success:** `200`, the meeting
- **Rules:** poll it while `processing_state` is `recording`, `queued` or `processing`
  (FR-014).
- **Errors:**
  - `404 NOT_FOUND`: no such meeting, or the caller cannot read it (section 6.4).

#### `PATCH /meetings/{meeting_id}` · Rename or move a meeting

- **Status:** Stub · **Caller:** any member who can read it · **Success:** `200`, the meeting
- **Rules:**
  - Renaming clears `name_is_generated`.
  - Moving keeps the recording, transcript and notes, and later notes use the new folder as
    context (FR-035). The target folder must belong to the same workspace.
  - `recorded_at` cannot be changed (FR-033). Since unknown fields are refused, sending it is
    a `422`.
- **Errors:**
  - `404 NOT_FOUND`: no such meeting, or the caller cannot read it.

#### `DELETE /meetings/{meeting_id}` · Delete a meeting

- **Status:** Stub · **Caller:** its recorder, a Moderator or the Owner · **Success:** `204`
- **Rules:** deletes the recording, transcript and notes (FR-036). Notes of other meetings
  that used it as context keep their text.
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller can read the meeting but did not record it, and is a
    plain member.
  - `404 NOT_FOUND`: no such meeting, or the caller cannot read it.

#### `GET /meetings/{meeting_id}/recording` · Get a playback link

- **Status:** Designed · **Caller:** any member who can read it · **Success:** `200`, a
  presigned link valid for 5 minutes
- **Rules:** the link is issued only after the access check. Storage paths are never exposed.
- **Errors:**
  - `404 NOT_FOUND`: no such meeting, or the caller cannot read it.
  - `409 RECORDING_NOT_READY`: the meeting is still being captured.
  - `410 RECORDING_DELETED`: retention removed the audio after 3 months (FR-046). The
    transcript and notes stay.

#### `GET /meetings/{meeting_id}/transcript` · Get the transcript

- **Status:** Stub · **Caller:** any member who can read it · **Success:** `200`, the current
  revision
- **Rules:**
  - Timestamped segments with speaker labels (FR-027).
  - Designed, not in the stub: `?revision_id=` selects another revision. The original is
    always reachable through `original_revision_id` (NFR-006, NFR-011).
- **Errors:**
  - `404 NOT_FOUND`: no such meeting, or the caller cannot read it; or no such revision.
  - `409 NOT_TRANSCRIBED`: the meeting is not processed yet.

#### `GET`, `POST /meetings/{meeting_id}/transcript/revisions` · List revisions or edit

- **Status:** Designed · **Caller:** any member who can read it · **Success:** `200`, a page
  of revisions, newest first; `201`, the new current revision
- **Rules:**
  - An edit applies text corrections and speaker renames as a new revision. Earlier revisions,
    the original included, never change (FR-028).
  - A rename applies to every segment of that speaker (FR-017).
  - `base_revision_id` must be the current revision, so a concurrent edit is refused instead
    of being silently overwritten.
  - Every segment and speaker id must belong to the base revision, and each may appear once.
- **Errors:**
  - `404 NOT_FOUND`: no such meeting, or the caller cannot read it.
  - `409 NOT_TRANSCRIBED`: the meeting is not processed yet.
  - `409 STALE_REVISION`: someone edited after `base_revision_id`. Reload and edit again.

### 4.5 Notes and export

#### `GET /meetings/{meeting_id}/notes` · List the notes

- **Status:** Stub · **Caller:** any member who can read it · **Success:** `200`, a page of
  versions, newest first; the first is current
- **Rules:** each version lists the meetings used as context (FR-020). A meeting without notes
  answers with an empty page.
- **Errors:**
  - `404 NOT_FOUND`: no such meeting, or the caller cannot read it.

#### `POST /meetings/{meeting_id}/notes` · Regenerate the notes

- **Status:** Stub · **Caller:** any member who can read it · **Success:** `202`, the queued
  job; `Location` points to the meeting to poll
- **Rules:**
  - `preset` defaults to the workspace's. `use_builtin_model` bypasses a configured provider,
    for example after it failed (FR-023).
  - One run may be in progress at a time. Each meeting has a configured number of
    regenerations, 3 by default (FR-025).
  - The transcript is never regenerated. A failed run keeps the previous notes current
    (FR-026).
- **Errors:**
  - `404 NOT_FOUND`: no such meeting, or the caller cannot read it.
  - `409 NOT_TRANSCRIBED`: there is no transcript to write notes from.
  - `409 NOTES_IN_PROGRESS`: a run is already queued or running.
  - `409 REGENERATION_LIMIT`: the meeting used up its regenerations.

#### `GET /meetings/{meeting_id}/transcript/export` · Download the transcript

- **Status:** Designed · **Caller:** any member who can read it · **Success:** `200`, a
  Markdown or WebVTT attachment
- **Rules:**
  - `format` is `markdown` (the default) or `vtt`. `timestamps=false` drops timestamps from
    Markdown; VTT always has them.
  - The current revision, split by speaker labels (FR-040, FR-041).
  - The file opens with a notice not to share it without the participants' permission and
    ends with an attribution (FR-042). An edited transcript says so.
- **Errors:**
  - `404 NOT_FOUND`: no such meeting, or the caller cannot read it.
  - `409 NOT_TRANSCRIBED`: the meeting is not processed yet.

#### `GET /meetings/{meeting_id}/notes/export` · Download the notes

- **Status:** Designed · **Caller:** any member who can read it · **Success:** `200`, a
  Markdown attachment
- **Rules:** the current notes, with their context meetings, the notice and the attribution
  (FR-040, FR-042).
- **Errors:**
  - `404 NOT_FOUND`: no such meeting, or the caller cannot read it.
  - `409 NO_NOTES`: the meeting has no notes yet.

### 4.6 Access and sharing

#### `GET`, `PUT /meetings/{meeting_id}/access` · Who can read a meeting

- **Status:** Designed · **Caller:** any member who can read it, to read; Moderator or Owner,
  to change · **Success:** `200`, the access setting
- **Rules:**
  - `PUT` replaces the whole setting (FR-037). A `restricted` meeting needs a non-empty
    `member_ids`, and every id must be a member. A `workspace` meeting takes an empty list.
  - A restricted meeting is withheld from everyone not selected, on every path: lists, direct
    links, exports, MCP, and the notes context of other meetings.
  - A Moderator who leaves themselves out loses access too.
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: a plain member tries to change it.
  - `404 NOT_FOUND`: no such meeting, or the caller cannot read it.

#### `GET`, `POST /meetings/{meeting_id}/shares` · List or create shares

- **Status:** Designed · **Caller:** any member who can read it · **Success:** `200`, a page
  of shares, revoked ones included; `201`, the new share with its link, shown once
- **Rules:**
  - Opening the link grants nothing by itself. The recipient signs in and requests access,
    and the share's creator approves one account (FR-038).
  - The recipient reads the transcript and notes only: no recording, export or onward share.
  - `redact_speaker_names` replaces speaker names for the recipient.
- **Errors:**
  - `404 NOT_FOUND`: no such meeting, or the caller cannot read it.

#### `DELETE /shares/{share_id}` · Revoke a share

- **Status:** Designed · **Caller:** the share's creator · **Success:** `204`
- **Rules:** the link and the bound recipient lose access at once. Revoking twice is harmless.
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller can read the meeting, but did not create the share.
  - `404 NOT_FOUND`: no such share, or the caller cannot read its meeting.

#### `POST /shares/{share_id}/access-requests` · Request access with a share link

- **Status:** Designed · **Caller:** any signed-in user · **Success:** `201`, the pending
  request
- **Rules:**
  - The body carries the link's token.
  - The creator is notified with the requester's name and email, and no meeting content.
  - A share link never creates an account (FR-047). An account can ask once per share.
- **Errors:**
  - `404 LINK_INVALID`: the share link cannot be used.
  - `409 ACCESS_REQUEST_EXISTS`: this account already asked.
  - `409 ALREADY_HAS_ACCESS`: the account is a member who can read the meeting, or the share
    is already bound to it.

#### `GET /shares/{share_id}/access-requests` · List requests for a share

- **Status:** Designed · **Caller:** the share's creator · **Success:** `200`, a page of
  requests, newest first
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller did not create the share.
  - `404 NOT_FOUND`: no such share, or the caller cannot read its meeting.

#### `POST /share-access-requests/{request_id}/approve` and `…/decline` · Decide a request

- **Status:** Designed · **Caller:** the share's creator · **Success:** `200`, the decided
  request
- **Rules:**
  - Approving binds the share to the requester's account. Any other account opening the link
    sees nothing (NFR-008).
  - A declined requester cannot ask again through this share.
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller did not create the share.
  - `404 NOT_FOUND`: no such request, or the caller cannot see its share.
  - `409 ACCESS_REQUEST_NOT_PENDING`: the request was already decided.
  - `409 SHARE_ALREADY_BOUND`, approval only: another account was approved.
  - `409 SHARE_REVOKED`, approval only: the share was revoked in the meantime.

#### `GET /shares/{share_id}/transcript` and `/shares/{share_id}/notes` · Read as a recipient

- **Status:** Designed · **Caller:** the account the share is bound to · **Success:** `200`,
  the transcript, or a page of notes
- **Rules:** with redaction, speaker names are replaced in both.
- **Errors:**
  - `404 NOT_FOUND`: no such share, or it is not bound to the caller.
  - `409 NOT_TRANSCRIBED`, transcript only: the meeting is not processed yet.
  - `410 SHARE_REVOKED`: the creator revoked the share.

#### `GET /users/me/shares` · Meetings shared with me

- **Status:** Designed · **Caller:** any user · **Success:** `200`, a page of shares bound to
  the caller and not revoked
- **Errors:** common only.

### 4.7 Capture

All capture operations accept the extension's bearer token as well as the browser session.

#### `GET /captures/destinations` · Where a recording can go

- **Status:** Designed · **Caller:** any user · **Success:** `200`, a page of workspaces,
  each with its folders
- **Rules:** the extension files a recording in a folder before it is processed, because the
  folder is the notes context (FR-012, FR-019).
- **Errors:** common only.

#### `POST /captures` · Start recording

- **Status:** Designed · **Caller:** any member of the target workspace · **Success:** `201`,
  the open capture
- **Rules:** `consent_confirmed` must be `true` (FR-009), and it is stored with the meeting.
  The meeting is created in state `recording`.
- **Errors:**
  - `404 NOT_FOUND`: no such workspace, or the caller is not a member.

#### `GET /captures/{capture_id}` · Get a capture

- **Status:** Designed · **Caller:** the account that opened it · **Success:** `200`, the
  capture with `received_seqs`
- **Rules:** lets the extension resume after a lost connection and upload only what is
  missing.
- **Errors:**
  - `404 NOT_FOUND`: no such capture, or another account opened it.

#### `PUT /captures/{capture_id}/chunks/{seq}` · Upload one chunk

- **Status:** Designed · **Caller:** the account that opened it · **Success:** `201` when
  stored; `200` when the same chunk was already stored
- **Rules:**
  - Multipart: `audio` (`audio/*`) and `speaker_events` (the active speakers seen on the Meet
    page).
  - The method is `PUT` because the sequence number identifies the chunk (section 6.8).
- **Errors:**
  - `404 NOT_FOUND`: no such capture, or another account opened it.
  - `409 CHUNK_MISMATCH`: different audio for a sequence number already stored.
  - `409 CAPTURE_CLOSED`: the capture was completed or finalised.
  - `413 PAYLOAD_TOO_LARGE`: the chunk exceeds `max_chunk_bytes`.
  - `415 UNSUPPORTED_MEDIA_TYPE`: the part is not `audio/*`.

#### `POST /captures/{capture_id}/complete` · Finish recording

- **Status:** Designed · **Caller:** the account that opened it · **Success:** `200`, the
  assembled capture
- **Rules:**
  - Assembles chunks `0..last_seq` and queues the meeting, through the same path as an upload
    (FR-012).
  - Repeating it with the same `last_seq` returns the same result.
  - If the extension never completes, the server finalises the chunks it has as a `partial`
    recording after a timeout.
- **Errors:**
  - `404 NOT_FOUND`: no such capture, or another account opened it.
  - `409 MISSING_CHUNKS`: some numbers below `last_seq` never arrived; `details` lists them.
  - `409 EMPTY_CAPTURE`: no chunk arrived at all.
  - `409 CAPTURE_CLOSED`: the capture was already finalised with a different `last_seq`.

### 4.8 Administration and operations

#### `GET /admin/jobs`, `GET /admin/metrics` · Operational dashboard

- **Status:** Designed · **Caller:** administrator · **Success:** `200`, a page of jobs, or
  the current metrics
- **Rules:** queue depth, waiting times, failures and load (FR-045). Never any recording,
  transcript or notes content.
- **Errors:**
  - `403 INSUFFICIENT_ROLE`: the caller is not an administrator.

#### `GET /health` · Liveness probe

- **Status:** Stub · **Caller:** public · **Success:** `200`, `{"status": "ok"}`
- **Rules:** for uptime monitoring. Not versioned.
- **Errors:** none.

## 5. Errors

### 5.1 Envelope

Every 4xx and 5xx response has one body. That includes FastAPI's own validation errors and
unknown routes:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request contains invalid fields",
    "details": [{"field": "email", "message": "value is not a valid email address", "provided_value": "alice@"}],
    "request_id": "req_4f9c2a1be07d"
  }
}
```

- **`code`** is a machine-readable enum, for clients to branch on. Every code an operation can
  return is listed in its documented responses.
- **`message`** is for people and may change. Clients never parse it.
- **`details`** names each invalid field, for validation errors.
- **`request_id`** equals the `X-Request-ID` response header. Server errors are logged with
  it and never echo internals.

### 5.2 Status codes

Each status code has one meaning:

- **`400`:** the body, or a JSON form field, cannot be parsed.
- **`401`:** there is no valid session; or, at sign-in, the credentials are wrong.
- **`403`:** the caller can see the resource, but their role forbids the action. Also used for
  a foreign origin, and for a feature this instance does not offer.
- **`404`:** the resource does not exist for this caller (section 6.4).
- **`409`:** the input is valid, but the current state forbids the request. The client must
  change the state first.
- **`410`:** the resource existed and was deliberately removed.
- **`413`, `415`:** the audio is too large, or is not audio.
- **`422`:** the input was parsed, but is invalid.
- **`429`:** a limit was reached. `Retry-After` says how many seconds to wait.

**Business limits are `429`, not `409`.** The invitation limits of FR-006 are rate limits: the
client's only remedy is to wait, which `429` and `Retry-After` express. A `409` would suggest
that changing the request could help.

### 5.3 Common errors

These apply to many operations, so section 4 does not repeat them:

- **`400 MALFORMED_REQUEST`:** any operation with a JSON body, when the body is not valid JSON.
- **`401 UNAUTHENTICATED`:** any operation that is not public, when the session cookie or
  token is missing, unknown, expired or ended. The response carries `WWW-Authenticate`.
- **`422 VALIDATION_ERROR`:** any operation with input, when a path parameter, query
  parameter or body field breaks its schema. This covers a wrong type, length, range or enum
  value; an unknown field; a broken cross-field rule; or an unknown `cursor`.
- **`403 ORIGIN_REJECTED`** *(designed)*: a `POST`, `PUT`, `PATCH` or `DELETE` that carries the
  session cookie and a foreign `Origin` header. Bearer requests are exempt (section 6.2).
- **`422 IDEMPOTENCY_KEY_REUSED`** *(designed)*: an `Idempotency-Key` sent again with a
  different body (section 6.8).
- **`409 IDEMPOTENCY_KEY_IN_USE`** *(designed)*: an `Idempotency-Key` whose first request is
  still running.
- **`429 RATE_LIMITED`:** the reverse proxy's per-address limit. It is documented on sign-in
  and on the registration and reset requests, where it matters most.
- **`404 NOT_FOUND`, `405 METHOD_NOT_ALLOWED`:** an unknown path, or a method the path does
  not support.
- **`500 INTERNAL_ERROR`:** an unexpected failure. The body carries only the `request_id`.

### 5.4 Error catalogue

Every code, grouped by status. Each entry says when the code is returned, why it has that
status, and which operations return it.

**`401 Unauthorized`**

- **`UNAUTHENTICATED`:** no valid session or token (section 5.3). An extension token on a
  non-capture endpoint is treated as no session (FR-003).
- **`INVALID_CREDENTIALS`:** sign-in with an unknown address or a wrong password. A single code
  for both, so the API cannot be used to check which addresses have accounts. Returned by
  `POST /sessions`.

**`403 Forbidden`**

- **`INSUFFICIENT_ROLE`:** the caller can see the resource, but their role does not allow the
  action:
  - Owner-only: workspace settings, deletion, the notes provider;
  - Moderator or Owner: members, invitations, folders, meeting access;
  - author, Moderator or Owner: glossary terms; the recorder, a Moderator or the Owner:
    meeting deletion;
  - share creator: revoking a share and deciding its requests;
  - administrator: the dashboard.
- **`ORIGIN_REJECTED`:** a state-changing cookie request from a foreign origin (section 5.3).
- **`INVITE_ONLY_INSTANCE`:** registration or a password reset was requested on an invite-only
  instance (FR-001, FR-048). It is `403` because the feature exists but this instance does not
  offer it. Returned by `POST /registrations` and `POST /password-resets`.
- **`EMAIL_MISMATCH`:** an invitation was accepted with a valid token, but the signed-in
  account has a different address. It is `403` because the link is fine, and this account may
  not use it. Returned by `POST /invitations/{id}/accept`.

**`404 Not Found`**

- **`NOT_FOUND`:** the resource does not exist, or the caller cannot see it. Seeing includes
  membership, a meeting restriction, and the binding of a share (section 6.4). Returned by
  every operation with an id in its path, except the link operations.
- **`LINK_INVALID`:** a registration, reset, invitation or share link cannot be used. One code
  covers an unknown id, a wrong token, and an expired, used, replaced or cancelled link
  (section 6.3). Returned by the `…/complete`, `…/preview`, `…/accept`, `…/register`,
  `…/decline` link operations and `POST /shares/{id}/access-requests`.

**`409 Conflict`**

- **`PERSONAL_WORKSPACE`:** deleting the personal workspace (FR-008), or inviting into it
  (FR-006). Returned by `DELETE /workspaces/{id}` and `POST /workspaces/{id}/invitations`.
- **`OWNER_IMMUTABLE`:** changing the Owner's role or removing the Owner. A workspace always has
  exactly one Owner. Returned by `PATCH` and `DELETE /workspaces/{id}/members/{user_id}`.
- **`ALREADY_MEMBER`:** inviting an address that belongs to a member, or accepting into a
  workspace the account already belongs to.
- **`ACCOUNT_EXISTS`:** registering through an invitation for an address that has an account.
  The client should sign in and accept instead.
- **`INVITATION_NOT_PENDING`:** cancelling an invitation that was already accepted, declined
  or cancelled.
- **`DEFAULT_FOLDER`:** deleting the default folder, which receives the meetings of deleted
  folders (FR-034).
- **`FOLDER_EXISTS`, `TERM_EXISTS`:** a folder name or a glossary term that already exists in
  the workspace, ignoring case.
- **`NOT_TRANSCRIBED`:** the meeting has no transcript yet, because it is recording, queued,
  processing or failed. Returned by the transcript, revision, notes regeneration, transcript
  export and shared transcript operations.
- **`STALE_REVISION`:** a transcript edit based on a revision that is no longer current. It
  prevents a lost update between two editors.
- **`RECORDING_NOT_READY`:** a playback link for a meeting that is still being captured.
- **`NOTES_IN_PROGRESS`:** a regeneration while another run of the same meeting is queued or
  running (FR-025).
- **`REGENERATION_LIMIT`:** a regeneration beyond the meeting's limit, 3 by default (FR-025).
  It is `409`, not `429`, because waiting does not help: the limit is per meeting, not per
  period.
- **`NO_NOTES`:** a notes export for a meeting without notes.
- **`ACCESS_REQUEST_EXISTS`, `ALREADY_HAS_ACCESS`:** a share access request that is pointless:
  the account already asked, or can already read the meeting.
- **`ACCESS_REQUEST_NOT_PENDING`, `SHARE_ALREADY_BOUND`:** deciding a request that was already
  decided, or approving a second account for a share that is bound to one (NFR-008).
- **`SHARE_REVOKED`:** approving a request for a revoked share.
- **`CHUNK_MISMATCH`:** different audio for a chunk number that is already stored. Identical
  audio is accepted as a retry.
- **`CAPTURE_CLOSED`:** a chunk for a finished capture, or completing it again with a
  different `last_seq`.
- **`MISSING_CHUNKS`, `EMPTY_CAPTURE`:** completing a capture with gaps, or with no audio.
  `details` lists the missing numbers.
- **`IDEMPOTENCY_KEY_IN_USE`:** see section 5.3.

**`410 Gone`**

- **`RECORDING_DELETED`:** the recording was removed by the 3-month retention rule (FR-046).
  It is `410` rather than `404` so the client can explain that the transcript and notes still
  exist. Returned by `GET /meetings/{id}/recording`.
- **`SHARE_REVOKED`:** the bound recipient reads a share that its creator revoked. It is
  `410`, because the recipient knew the share and should learn that it ended.

**`413`, `415`, `422`, `429` and `5xx`**

- **`PAYLOAD_TOO_LARGE`** (`413`): an upload over 500 MiB, or a chunk over `max_chunk_bytes`.
- **`UNSUPPORTED_MEDIA_TYPE`** (`415`): an upload or chunk that is not `audio/*`.
- **`VALIDATION_ERROR`, `IDEMPOTENCY_KEY_REUSED`** (`422`): see section 5.3.
- **`INVITATION_LIMIT`** (`429`): the caller invited 20 addresses in the last day (FR-006).
- **`INVITATION_COOLDOWN`** (`429`): the address was invited to this workspace in the last
  day, cancelled and declined invitations included (FR-006). It applies in `verified` mode
  only.
- **`RATE_LIMITED`** (`429`): see section 5.3.
- **`MALFORMED_REQUEST`** (`400`), **`METHOD_NOT_ALLOWED`** (`405`), **`INTERNAL_ERROR`**
  (`500`): see section 5.3. **`HTTP_ERROR`** covers any other status the framework raises.

## 6. Design decisions

### 6.1 Code-first with FastAPI and Pydantic

The specification is produced by FastAPI from route decorators and Pydantic models, so it
matches what the server does. The server serves it at `/openapi.json`, renders Swagger UI at
`/api-docs`, and writes `docs/api/openapi-generated.yaml` and `.json` on startup. Running
`python -m api.openapi_export` writes the same files without starting the server, which is what
CI and the Pages deployment use.

Pydantic was chosen as the single modelling tool for request validation, responses and,
later, the job contracts between the backend and the workers (high-level design, dependency
rule 1). FastAPI was chosen over Django REST Framework and Django Ninja for its native OpenAPI
3.1 generation and its integration with Pydantic. The cost is that sessions, password hashing
and migrations, which Django provides, are assembled by hand.

### 6.2 Authentication: server-side sessions, not JWT

The browser receives an `HttpOnly`, `Secure`, `SameSite=Strict` cookie that holds a random
token. The server stores only its hash in `SESSION` (data model), as threat-model risk R-01
prescribes. JWTs in the response body were rejected for three reasons:

- JavaScript can read them, so a single XSS bug would leak them.
- Their main advantage, verification without a session store, buys nothing in a monolith.
- Sign-out, and the password reset that ends every session (FR-048), need server-side state
  anyway.

Rules that follow from this:
- **Lifetimes are fixed and never extended by use** (FR-003): 14 days for a browser session,
  24 hours for an extension token.
- **The extension signs in with `kind: extension`** and receives a bearer token once. It
  works only on the capture endpoints and for sign-out, so a stolen extension token cannot
  read meetings.
- **State-changing requests from a foreign `Origin` are refused** with `403 ORIGIN_REJECTED`,
  unless they carry a bearer token. This is the CSRF defence for cookie requests. *Designed;
  not in the stub.*
- **MCP uses personal keys** (FR-043), shown once and stored hashed.

The stub accepts one demo account and a fixed session token.

### 6.3 Link tokens: identifier in the path, token in the body

Registration, password-reset, invitation and share links have the form
`https://<host>/<kind>/<id>#token=<token>`:
- **The `id`** is not secret. It is how Moderators list and cancel invitations.
- **The token** sits in the URL fragment, which browsers never send to a server. The web app
  sends it to the API in the request body, never in a path or query string, so tokens stay
  out of access logs and `Referer` headers (R-25).

Every refusal of a link is the same `404 LINK_INVALID`, whatever the cause:
- an unknown id or a wrong token;
- an expired, used, replaced or cancelled link;
- an invitation whose creator lost the Moderator role.

A holder of a dead link learns nothing about why it died, and the scheduler deletes expired
rows anyway. The only exceptions apply when the token is valid: `403 EMAIL_MISMATCH` and
`409 ACCOUNT_EXISTS`.

**Deliberate deviation:** `POST /invitations/{id}/preview` only reads, yet it is a `POST`. A
`GET` would need the token in the URL, which the rule above forbids.

### 6.4 Visibility: 404 for what the caller cannot see, 403 for what their role forbids

A resource the caller cannot see answers `404`, never `403`. That covers another workspace, a
restricted meeting the caller was not selected for (FR-037), and a share not bound to them
(NFR-008). A `403` would confirm that the resource exists.

`403 INSUFFICIENT_ROLE` is used only where the caller can see the resource but their role
does not allow the action, such as a Member inviting someone.

**Deliberate deviation:** the course lists "404 instead of 403" among the antipatterns. Here it
is the confidentiality requirement, applied consistently through one Access Policy (ADR-003).

### 6.5 Validation

Pydantic validates all input before a handler runs:
- **Types, lengths, ranges, enums and email syntax**, with a description and an example on
  every field.
- **Unknown fields and query parameters are rejected** (`extra="forbid"`), so a typo is never
  silently ignored. For example, `recorded_at` cannot be changed (FR-033).
- **Separate Create, Update and Read models**, so a provider API key can be written but never
  read back (NFR-013).
- **Cross-field rules**, such as an ordered date range, at least one field in a `PATCH`, and
  members for a `restricted` meeting, through `model_validator`.
- **Rules that need stored data**, such as duplicate terms, folders of another workspace and
  stale revisions, are checked by the services and answer with the same envelope.

### 6.6 Pagination

Every list returns `{"items": [...], "pagination": {"limit", "next_cursor", "has_more"}}`.
`limit` is between 1 and 100 and defaults to 20. Cursor pagination was chosen over offsets for
three reasons:
- the meeting list grows as the user scrolls (FR-031), which is the course's own rule for
  choosing cursors;
- its cost does not grow with depth;
- an item created between two pages is not shown twice.

Cursors are opaque, and every list uses the same style. The designed cursor encodes the sort
key of the last item. The stub's cursor is the position of the next item, which is enough for
fixed data.

### 6.7 Long-running work

Transcription and notes run in workers, not in the request:
- **Regenerating notes** answers `202 Accepted` with the queued job. Its `Location` points to
  the meeting.
- **Completing a capture or uploading a file** creates the meeting in state `queued` at once.
- **Clients poll the meeting** until `processing_state` becomes `processed` or `failed`
  (FR-014). The meeting's `failure_reason` gives the cause without content (FR-023).

### 6.8 Idempotency and retries

- **Capture chunks are `PUT /captures/{id}/chunks/{seq}`.** The sequence number identifies the
  chunk and matches the data model's unique `(capture_session_id, seq)`. A repeat with the same
  audio returns `200` and stores nothing new; different audio for a stored number is `409`. An
  extension on a flaky connection can therefore retry blindly.
- **`POST /captures/{id}/complete` can be repeated** and returns the same result.
- **Other authenticated `POST`s accept an `Idempotency-Key` header**, kept for 24 hours. A
  repeat with the same key and body replays the first successful response, marked
  `Idempotent-Replayed: true`. Keys are scoped to the presented credential, so one client can
  never replay another's response. This matters most for starting a capture, uploading, and
  regenerating notes, where a retried request would otherwise use up one of the limited
  regenerations. *Designed; not in the stub.*

### 6.9 Status codes for success

- **`201 Created`** with a `Location` header for every operation that creates a resource with
  its own URL.
- **`202 Accepted`** where the work continues in a worker (section 6.7).
- **`204 No Content`** for deletions and sign-out.
- **`200 OK`** for the action sub-resources (`…/cancel`, `…/approve`), which return the changed
  resource, and for replacing a pending invitation in place.

### 6.10 Versioning

- **The major version is in the path** (`/api/v1`). The `info.version` of the specification
  follows semantic versioning.
- **v1 may change freely until the first release.** After that it changes only additively:
  new endpoints and new optional fields.
- **A breaking change creates `/api/v2` alongside v1.** v1 then answers with `Deprecation`,
  `Sunset` and a `Link` to its successor until it is switched off.
- **The client that actually needs this is the Chrome extension.** The SPA is deployed with
  the backend, but users update the extension themselves, so the Capture API is where v2 would
  be needed first.
- **`/health` is not versioned.**

### 6.11 MCP server: written by hand, not generated

The MCP server at `/mcp/` exposes four read-only tools: `list_meetings`, `search_meetings`,
`get_transcript` and `get_notes`.

In the design, the tools act as the owner of the presented MCP key and read through Access
Policy, so a restricted meeting stays invisible to an assistant (FR-044). The stub reads the
same demo data as the REST stubs and does not check keys yet.

Generating the server from the OpenAPI specification (`FastMCP.from_fastapi`) was rejected for
two reasons:
- **It would expose every endpoint as a tool, including deletions and sharing**, to an agent
  that reads transcript text written by other people. That is the prompt-injection path that
  already made the team drop user-written prompts.
- **It forwards one fixed credential**, so it cannot act as each key's owner.

The tools reuse the API's models and documentation, as FastMCP's authors recommend: a curated
tool set over automatic conversion.

### 6.12 Choices where the requirements are silent

- **Who manages folders:** Moderators and the Owner.
- **Who edits glossary terms:** any member can add one. Its author, a Moderator or the Owner
  can change or remove it.
- **Who renames or moves a meeting:** any member who can read it. Deleting it stays with its
  recorder, a Moderator or the Owner (FR-036).
- **What counts towards the regeneration limit (FR-025):** every requested run, failed ones
  included, because a failed run still used the model.
- **Restricting a meeting without selecting yourself:** allowed. You lose access too, as
  FR-037 states it.
- **Inviting into a personal workspace:** refused; FR-006 now says so.
- **Reading who can access a meeting:** `GET /meetings/{id}/access` was added so the web app
  can show the current setting before a Moderator changes it.

## AI Usage

This document and the API code were prepared with the assistance of Claude Code (Claude Opus
5.5). The design follows the Backend Lead's decisions taken in working sessions on 2026-10-03
and 2026-10-04, and the requirements merged in PR #46. The stub code was checked with a type
checker and with scripted requests against every implemented operation. The author reviewed
and edited the content, and the document is reviewed through a pull request before merging.
