# Database implementation

Whadio stores structured data in PostgreSQL. Audio files live in object storage; the database
stores their references. This guide explains where the schema lives, how to apply it, and which
rules PostgreSQL enforces.

**Implemented:** SQLAlchemy models, Alembic migrations, shared transactions, and Access Policy,
Meetings and Retention services. Meeting content, folders, glossary, shares, exports and MCP
use PostgreSQL. Accounts routes persist sessions, workspaces and personal MCP keys; Capture and
notification delivery still need integration. Content routes require stored browser sessions or
personal MCP keys, and the development-user command creates a local account for the SPA.

Access Policy and Meetings emit typed content audit events through `audit/contracts.py`.
The runtime wires Audit's writer through the `content_audit` dependency using the same database
session as the change. The writer flushes events without committing; failure rolls back the
event and the change together.

Meetings persistence implements ingest and hosted capacity eviction. Processing owns orchestration,
processing-state decisions and regeneration limits. The runtime injects its `IMeetingProcessing`
port for durable job reservation; the default adapter refuses requests until connected.
Processing uses `MeetingService.processing_snapshot()` to lock and authorize before deciding,
then `save_processing_state()` to persist its state, sanitized failure code and absolute
regeneration count in the same transaction. Meetings does not choose transitions or enforce limits.
`save_initial_transcript()` atomically stores the original revision, speakers and segments with
its source job ID. Replaying that job returns the current version without overwriting edits;
a different job cannot replace an existing transcript. `MeetingPersistence.save_generated_notes()`
preserves earlier notes and emits the successful-regeneration audit event; Processing separately
persists the resulting state. Notification delivery remains outside these modules' scope.

Upload cleanup is reserved in a separate committed transaction before writing storage. The ingest
transaction locks that cleanup row and removes it only alongside a successful meeting and job
reservation. A rollback or crash leaves a durable cleanup task. `SKIP LOCKED` keeps the scheduler
from removing an upload in progress.

`IMeetingProcessing` lives in `meetings/processing.py`, so Processing can implement the port
without importing the web runtime. `create_app(integrations=RuntimeIntegrations(...))` accepts
session-bound factories for Processing, share-request notices and eviction notices. Each receives
the same `AsyncSession` as the use case and Audit; it must reserve durable work without committing
or publishing before commit. Absent adapters explicitly refuse work with
`INTEGRATION_UNAVAILABLE`, including hosted eviction. Tests' adapters are not production delivery.

Hosted ingest locks capacity before selecting old meetings, creates the triggering meeting and
records its ID in eviction audit details. Before deletion, Access Policy snapshots the uploader
and the old creator (only while still a member), deduplicates them and checks workspace or active
bound-share read access. `IEvictionNotifier` reserves each `EvictionNotice` with the old name only
for authorized recipients. The snapshot survives deletion; notice failure aborts the whole ingest.
Successful regeneration records its actual preset in audit details, without content or names.

Remaining integrations belong to their module owners:

- **Processing (Denys):** durable job reservation/publication, provider selection, transitions,
  regeneration limits, result consumption and idempotent calls to Meetings' persistence ports.
- **Notifications (after MVP owner assignment):** transactional durable adapters for share requests,
  eviction and retention warnings, deduplication and delivery. The scheduler accepts a session-bound
  `IRetentionNotifier` factory; its executable still defaults to the explicitly unavailable
  adapter. Seven-day warnings are not delivered yet.
- **Accounts (Denys):** replace demo sign-in/workspace administration with persisted accounts,
  sessions and membership writes. Stored-identity reads and membership/capacity interfaces are
  implemented, but normal demo sign-in does not establish an identity for meeting routes.
- **Capture (unassigned):** submit verified recordings through ingest and reserve Processing work.

These ports complete the integration boundaries of this slice, not end-to-end MVP behavior.
Retention deletion and recording cleanup continue independently of unavailable warning delivery.

## Where the schema lives

Three kinds of files work together:

| Location | Purpose |
| --- | --- |
| `src/whadio/<module>/models.py` | Defines the module's tables, columns, foreign keys, checks, and indexes in Python using SQLAlchemy. |
| `src/whadio/migrations/versions/` | Contains the packaged changes that create or upgrade a database, including triggers and privileges. |
| `src/whadio/migrations/env.py` | Loads the module models so Alembic can compare database structure with SQLAlchemy metadata. |

Changing a model does not update an existing database. A migration applies that change. Some
safeguards, such as triggers and audit privileges, are defined in migrations rather than model
metadata, so `Base.metadata.create_all()` is not a substitute for running Alembic.

The [data model](data-model.md) defines the entities and integrity rules. The
[high-level design](high-level-design.md) defines module responsibilities. This implementation
maps the domain entities and the implementation-only cleanup queue to these owners:

| Module | Tables it owns |
| --- | --- |
| Accounts & Workspaces | user, workspace, workspace_membership, invitation, pending_registration, password_reset, session, llm_provider_config, mcp_key |
| Meetings | folder, meeting, transcript, transcript_revision, speaker, transcript_segment, glossary_term, note, note_context_meeting, recording_deletion |
| Access Policy | meeting_access_grant, external_share, share_access_request |
| Capture | capture_session, capture_chunk |
| Processing | processing_job |
| Notifications | notification_outbox |
| Audit | audit_event |

A module needs `models.py` when it owns tables. Retention owns no table in this schema: it will
request recording-expiration data and state changes through Meetings. Other modules must use the
owning module's service interface instead of reading or writing its tables directly. Foreign keys
refer to table names, so one module's models do not import another module's models.

## Initial migration

Revision `0001` creates the complete initial schema: typed-value storage, defaults, keys,
indexes, integrity triggers, the original-transcript seal, folder-deletion guards and audit
privileges. Its SQL file holds the table-specific trigger functions. There is one initial
revision and no intermediate correction steps in that baseline.

Revision `0002` adds recording cleanup and warning state and case-insensitive glossary uniqueness.
Revision `0003` adds the nonnegative regeneration request counter. Existing actor-attributed notes
provide its initial lower bound; new requests, including ultimately failed runs, increment it in
the same transaction as job reservation. Downgrade refuses to discard nonzero counters.

The unreleased revisions were consolidated before deployment. Disposable databases created
with the earlier revision chain must be recreated; this migration is not an upgrade path for
that superseded development history. Future schema changes use new revisions. Review generated
migrations manually: metadata comparison cannot verify triggers or privileges.

Revision `0004` adds sanitized failure codes, original transcript job provenance and folder
recovery snapshots. Deleting a folder remembers its identity and the meetings moved to the default
folder; restoration recreates it and returns those surviving meetings in one audited transaction.
Restoration refuses name conflicts and later meeting moves. Workspace deletion removes recovery
snapshots. Downgrade refuses to discard populated recovery or processing provenance. Revision `0005` changes only the branch-added `failure_reason` column from TEXT to VARCHAR(20), matching the ORM enum. Its fixed-code CHECK remains intact, including on downgrade back to TEXT. No existing integrity triggers, privileges or locking rules change.

Revision `0006` records when a processing job was published and the context meetings a notes job
was sent with, so a job lost after its commit is published again.

Revision `0007` queues a capture chunk's audio in `recording_deletion` when its row is deleted, so
the chunks of an unfinished capture deleted with their meeting do not stay in storage.

Revision `0008` adds `notification_outbox`, owned by Notifications. Each row is one reserved
mail: its `kind`, the recipient's `recipient_user_id` (deleted with the account), a unique
`dedupe_key`, a JSONB `payload` object, and the delivery state `attempts`, `next_attempt_at`,
`sent_at` and a sanitised `last_error` of at most 200 characters. The partial index
`ix_notification_outbox_unsent` on `next_attempt_at WHERE sent_at IS NULL` serves the scheduler's
claim. `whadio_app` holds `SELECT`, `INSERT`, `UPDATE` and `DELETE` on it. Downgrade refuses to
discard unsent notices. The current head is `0008`.

Cleanup passes use UUID keyset windows and advance after each batch, including failed or locked
items. Each pass attempts each selected item at most once; failed items remain durable for the
next pass. API list cursors include the resource and caller scope and the final item's sort key.
List queries are bounded, note-context rows are fetched together, and visible folder counts are
aggregated for the returned page without loading meeting content.

## Notification outbox

`notifications.repositories.NotificationOutboxRepository` implements both sides of the outbox.
`INotificationOutbox.reserve()` inserts a notice in the caller's session with
`ON CONFLICT (dedupe_key) DO NOTHING`, so it commits or rolls back with the change it reports and a
repeated reservation is dropped. The payload is a pydantic notice from `notifications/templates.py`,
validated per `kind` again when it is read.

The scheduler sends what was reserved. Each pass, `NotificationDrainer` handles one due notice at
a time in three transactions. The first only claims it with `FOR UPDATE SKIP LOCKED`, counts the
attempt, moves `next_attempt_at` forward by a doubling, capped backoff and commits. The second
looks up the recipient's address through the `IRecipientDirectory` port, which the scheduler's
composition root answers from Accounts, and the template is rendered. The mail then goes to the
SMTP relay in a worker thread, with no transaction open. The third transaction marks the notice
sent, or stores a sanitised error. The lock keeps a concurrent scheduler off the notice while it
is claimed; after the commit, the future `next_attempt_at` does. An unexpected error while the
mail is composed or sent stops the pass, but the notice is already rescheduled, so the next pass
sends the others and retries it after its backoff. Delivery is at least once: a mail is sent
again when its outcome cannot be recorded, or when its send outlasts
`WHADIO_OUTBOX__RETRY_BACKOFF`. After `WHADIO_OUTBOX__MAX_ATTEMPTS` attempts a notice is given up. Each pass also deletes notices sent
longer ago than `WHADIO_OUTBOX__RETENTION`, and given-up ones reserved longer ago than it. Without
`WHADIO_SMTP__*` the scheduler sends nothing and deletes nothing, reservations still succeed, and
`WHADIO_PUBLIC_URL` is not needed. The batch size, backoff, attempts and retention are shown in
`.env.example`.

## Configure and apply the schema

For the local development stack, install dependencies with `uv sync`, copy `.env.example` to
`.env` if you do not already have one, and start the services with `uv run task infra:up`.
`.env.example` contains development examples; the actual `.env` must stay out of Git.

The PostgreSQL initialization script creates two roles when the data directory is first
initialized:

| Role | Password setting | Purpose |
| --- | --- | --- |
| `whadio_owner` | `WHADIO_DB_OWNER_PASSWORD` | Owns the schema and runs migrations. |
| `whadio_app` | `WHADIO_DB_APP_PASSWORD` | Runs application transactions; can read and write domain rows, but only insert and select audit events. |

Passwords come from the database's role setup; Alembic does not create them. Editing `.env` after
initialization does not change an existing PostgreSQL role's password. Application settings do
not require the owner password, and neither connection string is stored in `alembic.ini`.

`WHADIO_DB_HOST`, `WHADIO_DB_PORT`, and `WHADIO_DB_NAME` select the database for host-side commands.
The database port must match `POSTGRES_PORT` if the Compose port has been overridden. Use
`127.0.0.1` for host-side connections when IPv6 resolution of `localhost` is unavailable.

From the repository root, with the intended database selected:

```bash
WHADIO_DB_HOST=127.0.0.1 uv run whadio db-upgrade
WHADIO_DB_HOST=127.0.0.1 uv run alembic current
WHADIO_DB_HOST=127.0.0.1 uv run alembic check
```

`db-upgrade` applies migrations through the current head. `current` shows the applied revision.
`check` reports differences between the migrated schema and model metadata; it does not prove
that every business rule or trigger behaves correctly.

To inspect upgrade SQL without connecting to a database or providing credentials:

```sh
uv run alembic upgrade head --sql
```

## Rules enforced by PostgreSQL

Foreign keys, checks, and indexes validate relationships, enum values, case-insensitive email
uniqueness, token lookup uniqueness, membership uniqueness, pending invitation uniqueness, and
capture chunk sequence uniqueness. External shares have no recording option, matching
the API's transcript-and-notes-only contract.

Some checks run at transaction end so related rows can be created together. For example, a
workspace, its Owner membership, and its default folder can be inserted in one transaction; the
completed transaction must contain exactly one Owner and one default folder. A restricted meeting
must have at least one access grant, and every transcript must have exactly one original revision.
Removing a member must also remove their grants. Before removing the last selected recipient,
a Moderator explicitly selects another remaining member; removal never grants the Owner access
or unrestricts the meeting. The transaction must retain at least one selected recipient.

### Original transcript content

Create an original revision, its speakers, and its segments in one transaction. The database
stamps the implementation-only `transcript_revision.initialization_xid` with the top-level
transaction ID, overriding any caller-supplied value. Initial inserts and moves into the original
are allowed during that transaction, including through savepoints; later transactions are refused.
Original rows also reject updates, independent deletes, and moves out of the original. Edited
revisions cannot be relabelled as originals.

Deleting the containing transcript through a meeting or workspace cascade also deletes its
original content. Immutability preserves provenance while the meeting exists; it does not prevent
the required deletion of a meeting and its content.

### Folders and deletion

Folder names are unique per workspace ignoring case, including the default folder's name.
Folders and meetings cannot move between workspaces.

The Meetings service moves a nondefault folder's meetings to the default folder and writes one
audit event per move before deleting the folder, in the same transaction. Meeting IDs stay the same, preserving recording references, transcripts, notes, and
access rows. Rolling back the deletion also rolls back the moves. The default folder cannot be
deleted while its workspace exists.

Deleting a workspace instead cascades through its folders and meetings. Deleting a meeting
cascades through its dependent content and access rows. References to that meeting in other notes
become null, while their stored name snapshots and note text remain. SQL cascades remove database
rows; deleting the corresponding audio objects remains service work.

### Audit history

The application role cannot update, delete, or truncate existing audit events. Events have no
workspace or meeting foreign keys, so deleting those targets does not delete their history. An
event's actor references an existing account; account deletion is outside the current requirements.

These restrictions protect existing events. They do not automatically generate events or prevent
the application from inserting incorrect ones. The Audit writer accepts `MeetingMoved` and
`ContentEvent`; actions use the schema's `AuditAction` enum, and details contain IDs only.
Future actions must likewise use typed events without content or names.

## Rules that services must implement

Database safeguards protect stored data. Services enforce these use cases:

| Rule | Service responsibility |
| --- | --- |
| Folder permissions (FR-034) | Only Moderators and Owners may create, rename, or delete folders. Members may browse and move accessible meetings. |
| Meeting access (NFR-007, NFR-009, ADR-003) | Check permissions through Access Policy on every content path, including shares, exports, MCP, and folder context assembly. |
| Transcript edits (FR-028) | Save edits as edited revisions and expose the original with an edited marker. The API's promise to preserve earlier edited revisions must also be implemented by services. |
| Audit events (NFR-010, ADR-005) | Write actor-attributed events in the same transaction as the change. `FolderService.delete_folder` writes one `meeting_moved` event per moved meeting. The database trigger only refuses invalid deletion. |
| Recording retention (FR-046) | Delete audio 90 days after the meeting, warn accessible members seven days beforehand, and keep transcripts and notes. |
| Account and sharing flows | Share approval and revocation use services. Accounts writes and notification delivery remain unfinished. |

The retention interval and folder permissions above are confirmed product decisions. Storing
`recording_delete_after` and `recording_deleted_at` does not run a retention schedule or send a
warning. Retention uses injected storage and transactional notification collaborators; its
scheduler runs through `uv run whadio scheduler` (one instance per deployment), or
`uv run whadio scheduler --once` for one pass. It drains recording cleanup before scanning expiry,
continues after database failures and stops cleanly on SIGINT/SIGTERM. Configure storage with the
`WHADIO_STORAGE__*` variables and the interval with `WHADIO_RETENTION_INTERVAL_SECONDS`, shown in
`.env.example`. Warning delivery is deliberately unavailable until Notifications is connected;
failed warnings are not marked sent, and expiry and cleanup continue independently. The one-pass
command exits unsuccessfully if any work fails. Database tests exercise the service
and content-route behavior, but do not establish that those runtime integrations are complete.

## Transactions and verification

The shared `Database` helper creates async SQLAlchemy sessions. Its `database.transaction()`
context commits on success and rolls back on an exception. Future use cases must pass that same
session to all participating repositories, including Audit; repositories must not commit
independently. A session belongs to one use case and must not be shared across concurrent tasks.
The runtime that constructs `Database` must close it on shutdown. Application code generates UUIDs;
timestamps use timezone-aware PostgreSQL values.

The CLI loads migrations from the installed package, so `whadio db-upgrade` works outside a
checkout. `uv run task db:upgrade` is the repository shortcut. The migration environment is a
composition root; it imports each module's models without moving ownership out of that module.

Fixed-value columns use module-owned `StrEnum` types. Notes templates and provider values live
in Accounts and are reused by Meetings. Database CHECK constraints remain in force, and migrations retain
their own value snapshots rather than importing mutable application enums. Creation timestamps,
the straightforward false flags, and the processing retry counter have server defaults.

Pytest loads the shared fixtures in the repository's `conftest.py`. Fixtures create rows through
the ORM models; refusal tests may use raw SQL to exercise database safeguards. Database tests are marked
`slow` and need a migrated, disposable database. Set `WHADIO_TEST_DATABASE_URL` to its
`whadio_app` connection URL, then run `uv run task test`. Without that setting, database tests are
skipped: a passing fast suite is not database verification. CI starts PostgreSQL using Compose,
applies the packaged migrations as `whadio_owner`, checks schema drift, and runs the complete suite
as `whadio_app`. Local push hooks require the same connection URL to run database tests.

Most fixtures roll their transaction back. Original-sealing tests commit their initial data to
exercise a later transaction, then clean up only their own workspace and account. Never point
these tests at a database containing data you need to keep.

Verification must cover fresh and populated upgrades, downgrade/re-upgrade cycles, metadata
agreement, privilege denials, deferred invariants, provenance protection, folder preservation,
cascades, rollback, and concurrency. A full downgrade removes schema and data; perform downgrade
checks only on disposable databases.

Run `uv run task check` and the full test suite against a disposable database before relying on
database verification results.

The decision to retain database integrity guards and the original-transcript transaction seal is
recorded in [ADR-006](decisions/ADR-006.md). Services retain authorization and workflow decisions.

## Folder deletion

`meetings.services.FolderService.delete_folder` authorizes a Moderator or Owner, locks the
workspace and acting membership through `lock_role()`, then the source and default folders,
moves meetings with `UPDATE ... RETURNING`, writes one
`meeting_moved` event per returned ID, and deletes the empty folder. Wire `FolderRepository`,
`WorkspaceMembershipService` (with its `MembershipRepository`) and `AuditWriter` to the same
`Database.transaction()` session. Ordinary membership `role()` lookups are plain reads; only
`lock_role()` takes the workspace and membership locks needed by folder deletion. A failure
rolls back the moves, audit events and deletion together. The database trigger refuses direct
deletion of an occupied folder; workspace deletion still cascades. The HTTP folder endpoints
are implemented. Deletion also records the folder and moved meeting IDs in a recovery snapshot;
restoration refuses to overwrite subsequent moves and restores the surviving meetings atomically.


## AI Usage

This implementation guide was prepared and clarified with OpenAI Codex using the requirements,
architecture, models, migrations, and tests. The author reviewed and edited the content, and the document is reviewed through a pull request before merging.
