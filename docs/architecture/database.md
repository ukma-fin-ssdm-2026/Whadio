# Database implementation

Whadio stores structured data in PostgreSQL. Audio files live in object storage; the database
stores their references. This guide explains where the schema lives, how to apply it, and which
rules PostgreSQL enforces.

**Implemented:** SQLAlchemy models, Alembic migrations, the shared transaction helper, and
database regression tests. **Still unfinished:** repositories and business services. The HTTP API
continues to use demo fixtures; running migrations does not connect those routes to PostgreSQL.

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
maps their 25 entities to these owners:

| Module | Tables it owns |
| --- | --- |
| Accounts & Workspaces | user, workspace, workspace_membership, invitation, pending_registration, password_reset, session, llm_provider_config, mcp_key |
| Meetings | folder, meeting, transcript, transcript_revision, speaker, transcript_segment, glossary_term, note, note_context_meeting |
| Access Policy | meeting_access_grant, external_share, share_access_request |
| Capture | capture_session, capture_chunk |
| Processing | processing_job |
| Audit | audit_event |

A module needs `models.py` when it owns tables. Retention owns no table in this schema: it will
request recording-expiration data and state changes through Meetings. Other modules must use the
owning module's service interface instead of reading or writing its tables directly. Foreign keys
refer to table names, so one module's models do not import another module's models.

## Initial migration

Revision `0001` creates the complete initial schema: typed-value storage, defaults, keys,
indexes, integrity triggers, the original-transcript seal, folder-deletion guards and audit
privileges. Its SQL file holds the table-specific trigger functions. There is one initial
revision and no intermediate correction or downgrade steps.

The unreleased revisions were consolidated before deployment. Disposable databases created
with the earlier revision chain must be recreated; this migration is not an upgrade path for
that superseded development history. Future schema changes use new revisions. Review generated
migrations manually: metadata comparison cannot verify triggers or privileges.

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
the application from inserting incorrect ones. The Audit writer accepts a typed `MeetingMoved` event and assigns `meeting_moved` itself;
its details contain only source and destination folder IDs. Future actions need their own typed
events with IDs and enum values, never content or names.

## Rules that services must implement

Database safeguards protect stored data. Services still need to implement these use cases:

| Rule | Remaining service responsibility |
| --- | --- |
| Folder permissions (FR-034) | Only Moderators and Owners may create, rename, or delete folders. Members may browse and move accessible meetings. |
| Meeting access (NFR-007, NFR-009, ADR-003) | Check permissions through Access Policy on every content path, including shares, exports, MCP, and folder context assembly. |
| Transcript edits (FR-028) | Save edits as edited revisions and expose the original with an edited marker. The API's promise to preserve earlier edited revisions must also be implemented by services. |
| Audit events (NFR-010, ADR-005) | Write actor-attributed events in the same transaction as the change. `FolderService.delete_folder` already writes one `meeting_moved` event per moved meeting. The database trigger only refuses invalid deletion; other actions still need service integration. |
| Recording retention (FR-046) | Delete audio 90 days after the meeting, warn accessible members seven days beforehand, and keep transcripts and notes. |
| Account and sharing flows | Complete registration, enforce invitation throttling, approve external shares, and send notifications. |

The retention interval and folder permissions above are confirmed product decisions. Storing
`recording_delete_after` and `recording_deleted_at` does not run a retention schedule or send a
warning. Repositories and services remain unfinished, and the current HTTP fixtures do not verify
these use cases against the database.

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
remain designed and are wired by the API implementation.


## AI Usage

This implementation guide was prepared and clarified with OpenAI Codex using the requirements,
architecture, models, migrations, and tests. The author reviewed and edited the content, and the document is reviewed through a pull request before merging.

These PR #63 review revisions were assisted by OpenAI Codex. Everything was reviewed by me.
