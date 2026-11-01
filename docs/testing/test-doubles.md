# Test Doubles

A test double stands in for a collaborator that is slow, external or hard to control. The course
(`Reference/Test-Doubles.md`, Lecture 6 §3.6) names three kinds:

- **stub**: answers with values set in advance;
- **mock**: checks how the code under test used it;
- **fake**: works, as a simplified in-memory implementation.

The kind depends on what the test asserts, not on the class. The same `InMemoryObjectStorage` is a
fake when a test checks only the result, and a mock when the test asserts on the calls it recorded.

## Doubles per external dependency

| Dependency | Double | Kind | Where it lives |
|---|---|---|---|
| Database (PostgreSQL) | None in integration tests: the real database, each test in a transaction that is rolled back (`database_settings`, `async_database`, `database_session`) | (real) | `conftest.py` |
| Database, in unit tests | In-memory repositories: `FakeMeetingRepository`, `FakeAccessRepository`, `FakeJobs` | fake | `src/whadio/meetings/test_services_unit.py`, `src/whadio/access_policy/test_services_unit.py`, `src/whadio/processing/test_services.py` |
| Object storage (S3, SeaweedFS) | `InMemoryObjectStorage` | fake; mock when a test asserts on `uploaded`, `deleted`, `presigned` or `caller_threads` | `src/whadio/shared/fakes.py` |
| Object storage, the S3 client itself | `_FakeServer`, a urllib3 pool that answers every request with one status | stub, and mock for the recorded requests | `src/whadio/shared/test_storage.py` |
| Broker (RabbitMQ), in unit tests | `FakeDelivery`, `FakePublisher`, `FakeMessagePublisher` | mock | `src/whadio/processing/test_consumer.py` |
| Broker, in integration tests | None: the Compose stack's RabbitMQ, reached through the `rabbitmq_settings` fixture | (real) | `conftest.py` |
| Clock | `FixedClock`, a callable for the `now: Callable[[], datetime]` parameters, with `advance()`; `NOW`, the canonical instant | stub | `src/whadio/shared/fakes.py`, `conftest.py` |
| Audit log | `RecordingAuditWriter`, an `IContentAuditWriter` that keeps the events written | mock | `src/whadio/audit/fakes.py` |
| LLM (Anthropic) | `_Model` and `_FixedModel`, which return a fixed answer; `httpx2.MockTransport` under `ClaudeChatModel` | stub | `src/whadio/workers/notes/test_handler.py`, `test_main.py`, `test_claude.py` |
| LLM, shared | `ScriptedChatModel` (**planned**, in a later PR with the chunked notes) | stub | `src/whadio/workers/notes/` |
| The REST API, in the frontend's tests | A Mock Service Worker `server` with handlers typed from the OpenAPI types | stub; mock when a test asserts on the requests `serveApi` recorded | `frontend/src/shared/testing/server.ts`, `frontend/src/app/testing.tsx` |
| SMTP | A recording mail sender (**planned**, in the Notifications PR) | mock | `src/whadio/notifications/` |
| Password hasher | None: the real `Argon2PasswordHasher` | (real) | `src/whadio/accounts/passwords.py` |

## Using the shared doubles

- `InMemoryObjectStorage(now=FixedClock(NOW))` keeps the objects in `objects` and records the keys
  in `uploaded`, `deleted` and `presigned`, and the calling threads in `caller_threads`. Set
  `fail_put` or `fail_delete` to make the call raise `ObjectStorageError`. Like the real storage,
  `presign_get` refuses a lifetime that is not a whole number of seconds from 1 s to 7 days.
- `FixedClock(at)` refuses a time that is not aware UTC, so a test cannot mix naive and aware times.
  It keeps the time in UTC, so `advance()` across a daylight saving change moves it by the full
  interval.
- `rabbitmq_settings` reads `WHADIO_BROKER__URL` from the environment or `.env`, and skips the test
  when it is unset, as `database_settings` does for `WHADIO_TEST_DATABASE_URL`.
- A shared double subclasses the Protocol it stands in for and marks its methods `@override`, so the
  type checkers report it as soon as the Protocol changes.

Local doubles stay where the interface differs: `RecordingStore`
(`src/whadio/retention/test_services.py`) and `DeletedKeys` (`src/whadio/api/test_composition.py`)
implement Retention's async recording port, not
`IObjectStorage`, and `_FakeServer` replaces the HTTP layer under the real S3 client.

## Why `world()` and `team()` stay separate

Both builders create a workspace Owner, a Member and a meeting, but they wire different services:

- `world()` (`src/whadio/access_policy/test_services.py`) builds an `AccessService` on the real
  PostgreSQL session, with its own repository and the real memberships, and fakes only the meeting
  scopes, the audit log and the share notices.
- `team()` (`src/whadio/meetings/test_services_unit.py`) builds a `MeetingService` entirely in memory, with
  `FakeMeetingRepository` and `FakePolicy` in place of the database and Access Policy.

A merged builder would have to wire both graphs behind options, and it could live in neither
module: import-linter forbids Access Policy, the lower layer, from importing Meetings. The two
builders now share the double they had in common, `RecordingAuditWriter`.

## AI Usage

Prepared with Claude Code (Claude Opus 5.5); reviewed by Andrii Shalaiev.
