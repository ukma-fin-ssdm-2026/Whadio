# Unit Testing and Coverage

Starting point: `main` at `ff3f913`, with 485 passing tests.

## 1. Unit tests

### Modules

We chose the two backend modules with the weakest coverage:

- **Access Policy** (`src/whadio/access_policy/`): who may open a meeting, restricted meetings, share links and access requests. Before this work it had no tests of its own for its services or repository. API tests reached it only indirectly.
- **Meetings** (`src/whadio/meetings/services.py`): the meeting use cases, such as upload, folders, transcripts and their edits, notes, the glossary, and the views behind a share link. It had the most untested lines of any file (99).

We added 116 tests in five files. The two `test_services_unit.py` files are unit tests: they replace every collaborator with an in-memory fake, need no running services and run in the push hook. The other three are integration tests against PostgreSQL, marked `slow`.

| File | Tests | What they cover |
|---|---|---|
| `access_policy/test_services_unit.py` (new, unit) | 16 | reading and restricting a meeting; creating, requesting, approving and revoking share links; what a share recipient may do; requester profiles |
| `meetings/test_services_unit.py` (new, unit) | 12 | creating a meeting, consent and the default folder; renaming and deleting; folders; the glossary |
| `access_policy/test_services.py` (new) | 42 | restricting a meeting and choosing its members; creating, requesting, approving, declining and revoking share links; requester profiles; who gets notified before a meeting is deleted |
| `access_policy/test_repositories.py` (new) | 7 | paging through shares, a recipient's shares and access requests with a cursor, including records created at the same moment; revoked shares are left out |
| `meetings/test_services.py` (extended) | 39 | refusals for create, update and delete; folders; folder counts; transcript edits and revisions; replaying a transcription job; shared transcripts and notes with and without speaker names hidden; the glossary; processing state |

### Fixtures, mocks and parametrised tests

- **Fixtures:** `async_database` (in the root `conftest.py`) runs each test in a PostgreSQL transaction that is rolled back afterwards, so tests never see each other's data. Two builders set up the people each test needs: `world()` in Access Policy and `team()` in Meetings. Each creates a workspace Owner, a Member, an outsider and a meeting.
- **Mocks (fakes):** Access Policy must not import Meetings (import-linter enforces the layering), so its tests replace the collaborators with small fakes. `FakeMeetings` returns the meeting's scope, `FakeAudit` records audit events in a list, and `FakeNotices` records the notices sent to share creators. The tests then assert on what the fakes received. The unit tests go further: `FakeAccessRepository` and `FakeDirectory` stand in for the Access Policy database and the workspace memberships, and `FakeMeetingRepository` and `FakePolicy` do the same for Meetings.
- **Parametrised tests:** the four content paths a share recipient may not use (export, MCP, recording, write); the two invalid combinations of access mode and member list; blank names and names with a control character; a share with names hidden and with names shown; deleting and updating someone else's glossary term.

### Edge cases covered

Access Policy:

- an access list that does not match the access mode, and a grant to someone outside the workspace;
- a wrong token and a revoked share, both treated as an invalid link;
- a second request for the same share, a request decided twice, approving a request to a revoked share, and deciding a request that does not exist;
- a share already bound to one recipient, and a recipient who already has access;
- revoking a share twice (audited once) and revoking a share that does not exist;
- a share recipient trying each of the four paths other than reading (export, MCP, recording, write);
- a revoked share stopping its recipient from reading;
- the second page of every cursor-paged list, with revoked shares left out;
- records created at the same moment, paged one at a time with no record missing or repeated;
- a share recipient counted as a reader before a meeting is deleted.

Meetings:

- an update or a transcript edit that changes nothing;
- a recording into, or a move to, a folder that does not exist, and an edit of a segment that does not exist;
- folder names that are blank, contain a control character, are already taken, or carry surrounding spaces (kept trimmed);
- a glossary term that differs from another only in letter case, a term citing a meeting of another workspace, a rename to another term's spelling, and an update that changes only some fields;
- a failed processing state without a failure reason;
- replaying the same transcription job versus a different job;
- a meeting with no transcript yet: no current transcript, and its revisions refused;
- folder counts that leave out meetings the member cannot see;
- a share that tries to open another meeting, and shared notes with speaker names hidden and shown.

### Arrange, Act, Assert

Every test follows the project's AAA layout, with one logical assertion per test:

```python
@pytest.mark.parametrize(
    "path", [ContentPath.EXPORT, ContentPath.MCP, ContentPath.RECORDING, ContentPath.WRITE]
)
def test_share_recipient_may_only_read(async_database: AsyncDatabase, path: ContentPath) -> None:
    # Arrange
    async def scenario(session: AsyncSession) -> Failure | None:
        unit = await world(session)
        created = await unit.access.create_share(unit.owner, unit.meeting, NOW, redact=False)
        share_id = created.share.share_id
        request = await unit.access.request_access(unit.outsider, share_id, created.token, NOW)
        await unit.access.decide(unit.owner, request.share_access_request_id, NOW, approve=True)
        return await refusal(unit.access.policy.authorize_share(share_id, unit.outsider, path))

    # Act
    failure = async_database.run(scenario)
    # Assert
    assert failure is Failure.INSUFFICIENT_ROLE
```

## 2. Coverage and iteration

### Tool

We used coverage.py through pytest-cov. Tests and migration files are left out of the numbers. The 4 tests that need downloaded ML models were not run.

The tests that need the models run with `uv run pytest -m models`, on a machine that has them. The NFR-002 timing test also needs `WHADIO_TEST_HOUR_RECORDING`, the path of a recording of about 60 minutes that is never committed; it is read from the environment only and skips without it. The [test plan](../validation/test-plan.md#бонуси) gives its command and results.

The integration tests need a migrated PostgreSQL database. Without `WHADIO_TEST_DATABASE_URL` they are skipped, and the report still comes out, only with different numbers. The setting is read from the environment only, not from `.env`, so export it in the shell that runs the tests ([database tests](../architecture/database.md) has the details):

```bash
cp .env.example .env
uv run task infra:up
uv run task db:upgrade
export WHADIO_TEST_DATABASE_URL=postgresql+psycopg://whadio_app:whadio-dev-app@127.0.0.1:5432/whadio
```

Invitation concurrency tests use independent committed transactions, including real audit writes.
They also need `WHADIO_DB_OWNER_PASSWORD` from the environment or `.env` to clean up their own
fixtures: the application role cannot delete append-only audit records. Cleanup connects to the
host, port and database from `WHADIO_TEST_DATABASE_URL`; the tested use cases still run as
`whadio_app`. Use a disposable test database.

Then measure with the command that CI runs. `task test:cov` refuses to start without `WHADIO_TEST_DATABASE_URL`, so skipped database tests cannot quietly change the number. The second command also writes the HTML report to `htmlcov-ci/`:

```bash
uv run task test:cov
uv run task test:cov -- --cov-report=term-missing:skip-covered --cov-report=html
```

The run fails below 85% coverage of lines and branches combined: an `if` counts as covered only when both of its sides ran. The threshold is set in one place, `[tool.coverage.report]` in `pyproject.toml`. Test files, migration revisions and the shared test doubles (`fakes.py`) are left out of the numbers.

Coverage also follows greenlets (`concurrency = ["greenlet", "thread"]`). SQLAlchemy's async layer runs every database call in a greenlet, and without this setting coverage.py does not see the code that runs after an awaited call return, so it reports that code as never run. Turning it on raised the first full run from 84.7% to 85.6%. Nearly all of the gain is in database-backed code: the session and workspace routes went from 67% and 91% to 100%, the MCP server from 72% to 91%, and the meeting routes from 73% to 83%.

Why 85: the full run measures 87.5% of lines and branches combined. The testing strategy and this gate settled on 85 together, as a compromise: it sits close to the measured figure, so a real drop fails the run, while it leaves room for the ASR code that only runs with downloaded models, which CI cannot run (about 1.2 points), and for normal churn.

The HTML report colours each line green (run) or red (not run). `htmlcov-before/` shows the state before the new tests and `htmlcov/` the state after; both are snapshots kept for Lab 6. They, and the before-and-after figures below, were measured before coverage followed greenlets, so they undercount the database-backed modules. CI writes a fresh report on every run and uploads it with the JUnit XML as the `test-reports` artifact, and the job summary shows the coverage table and the failed tests.

### Before and after

| File | Before | After |
|---|---|---|
| `access_policy/repositories.py` | 77% | 100% |
| `access_policy/services.py` | 86% | 98% |
| `meetings/services.py` | 72% | 97% |
| `meetings/repositories.py` | 82% | 87% |
| Whole application | 85% | 88% |

### How the uncovered lines turned into tests

We read the missing lines from `--cov-report=term-missing` and wrote a test for each behaviour behind them. Most of them were refusals and edge cases that the API tests never reached:

- the paging cursors in the Access Policy repository were never used, because no test asked for a second page;
- `rename_folder`, `revisions`, `context`, `folder_count`, the whole glossary (`add_term`, `update_term`, `delete_term`) and the share views (`shared_transcript`, `shared_notes`) were never called from a test at all;
- the refusals and edge cases listed under "Edge cases covered" above.

### Is 100% coverage meaningful?

Not as a goal. 13 lines are still uncovered in the two service files. Two of them are ordinary gaps that a test could still close: renaming a glossary term successfully, and the happy path of `processing_snapshot`. The rest fall into two kinds:

- **Defensive re-raises:** for example, `except UseCaseError: if error.code == NOT_FOUND: ...; raise`. Reaching the bare `raise` needs a fake repository that throws an error the real one never throws. Such a test would check the fake, not Whadio.
- **Race guards:** for example, an access request that disappears between two reads under a row lock. Testing them properly needs two concurrent transactions. A test that fakes it reaches the line but proves nothing about the race.

Coverage says which code ran, not whether the test checked the right thing. A test without an assertion still raises coverage. In this pass, coverage was useful as a map of what nobody had tested. The value came from the assertions on refusals and edge cases. We'd rather keep the 88% with meaningful assertions than reach 100% with tests written to light up lines.

### Mutation testing

`uv run task mutation` runs mutmut over the notes prompt (`src/whadio/workers/notes/prompt.py`) against the notes worker's tests (`src/whadio/workers/notes/`), then lists the mutants that no test killed. `uv run mutmut show <name>` prints one of them as a diff. The scope is set in `[tool.mutmut]` in `pyproject.toml`. The task deletes `mutants/` first, because mutmut keeps a mutant's earlier verdict when only the tests have changed. The run stays out of the hooks and CI: run it by hand after changing the module or its tests. mutmut does not run on native Windows ([boxed/mutmut#397](https://github.com/boxed/mutmut/issues/397)); use WSL there.

## 3. Proposals for improving the tests

- **Close the two ordinary gaps:** a successful glossary term rename, and the happy path of `processing_snapshot`.
- **Measure branches, not only lines:** the runs above count lines. An `if` whose false side never ran still counts as covered. Adding `--cov-branch` would show those half-tested conditions.
- **Mutation testing:** run mutmut on `access_policy/services.py`. It flips conditions and changes values, then checks whether some test fails. Coverage shows that a line ran; mutation testing shows whether an assertion would notice it going wrong.
- **Real concurrency tests for the race guards:** two sessions against PostgreSQL, each holding its own transaction, instead of leaving those lines untested.
- **Property-based tests for name validation:** Hypothesis can generate arbitrary Unicode for folder names and glossary terms, including whitespace and control characters, instead of the few hand-picked values used now.
- **One shared builder:** `world()` and `team()` both create an Owner, a Member, an outsider and a meeting. Moving them into one fixture in `conftest.py` would stop the next module's tests from writing a third copy.

## 4. Frontend tests

The web app has its own tests, in `frontend/`, next to the code they test. They need neither the API nor a browser.

| Command, in `frontend/` | What it does |
|---|---|
| `npm test` | Runs every test once; `uv run task frontend:test` does the same from the root |
| `npm run test:watch` | Reruns the tests a change affects |
| `npm run coverage` | Runs every test and reports V8 coverage; no gate applies to it |
| `npm test -- --changed origin/main` | Runs the tests the branch can affect, as the push hook does |

- **Vitest and jsdom** run the tests. jsdom has no layout and applies no media query, and Vitest blanks imported CSS, so a test cannot see how a page looks. `src/app/theme/css-variables.test.tsx` reads the CSS that Emotion writes into its `<style>` nodes to check the theme's variables and every `var(--mui-...)` the sources reference. Look at a page in a browser to check its appearance.
- **Testing Library** renders components and finds them by role, label or text, as a user would. `renderWithProviders` (`src/shared/testing/render.tsx`) adds a fresh query client and the notification provider around a feature's component. It uses MUI's default theme, because shared code may not import the app's.
- **Mock Service Worker** answers the API. `src/shared/testing/server.ts` exports the `server` and an `http` typed from the OpenAPI types, so a handler for a path the API does not have fails to compile. A test declares its handlers with `server.use(...)`, and a request nothing handles fails the test. `src/shared/testing/fixtures.ts` builds the API's response bodies.
- **Route tests** render the real `<App />` at a URL, with the real route tree and the real theme: set the address with `window.history.replaceState`, then render. `App.routing.test.tsx` and `App.test.tsx` work this way. `src/app/testing.tsx` holds their helpers: `serveApi` answers a signed-in or signed-out session and records the requests, `signIn` fills in the form, and `renderAtPath` gives a component that holds links a router without the app.

## AI Usage

The tests, the coverage runs and this document were made with Claude Code (Claude Opus 5.5); checked by Denys Zabiiaka.
