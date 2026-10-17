# Unit Testing and Coverage

Starting point: `main` at `ff3f913`, with 485 passing tests.

## 1. Unit tests

### Modules

We chose the two backend modules with the weakest coverage:

- **Access Policy** (`src/whadio/access_policy/`): who may open a meeting, restricted meetings, share links and access requests. Before this work it had no tests of its own for its services or repository. API tests reached it only indirectly.
- **Meetings** (`src/whadio/meetings/services.py`): the meeting use cases, such as upload, folders, transcripts and their edits, notes, the glossary, and the views behind a share link. It had the most untested lines of any file (99).

We added 85 tests in three files:

| File | Tests | What they cover |
|---|---|---|
| `access_policy/test_services.py` (new) | 42 | restricting a meeting and choosing its members; creating, requesting, approving, declining and revoking share links; requester profiles; who gets notified before a meeting is deleted |
| `access_policy/test_repositories.py` (new) | 4 | paging through shares, a recipient's shares and access requests with a cursor; revoked shares are left out |
| `meetings/test_services.py` (extended) | 39 | refusals for create, update and delete; folders; folder counts; transcript edits and revisions; replaying a transcription job; shared transcripts and notes with and without speaker names hidden; the glossary; processing state |

### Fixtures, mocks and parametrised tests

- **Fixtures:** `async_database` (in the root `conftest.py`) runs each test in a PostgreSQL transaction that is rolled back afterwards, so tests never see each other's data. Two builders set up the people each test needs: `world()` in Access Policy and `team()` in Meetings. Each creates a workspace Owner, a Member, an outsider and a meeting.
- **Mocks (fakes):** Access Policy must not import Meetings (import-linter enforces the layering), so its tests replace the collaborators with small fakes. `FakeMeetings` returns the meeting's scope, `FakeAudit` records audit events in a list, and `FakeNotices` records the notices sent to share creators. The tests then assert on what the fakes received.
- **Parametrised tests:** the four content paths a share recipient may not use (export, MCP, recording, write); the two invalid combinations of access mode and member list; blank names and names with a control character; a share with names hidden and with names shown; deleting and updating someone else's glossary term.

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

```bash
uv run --with pytest-cov pytest -m "not models" --cov=whadio --cov-report=term-missing
uv run --with coverage coverage html --omit='*/test_*.py,*/migrations/versions/*'
```

The HTML report colours each line green (run) or red (not run). `htmlcov-before/` shows the state before the new tests and `htmlcov/` the state after.

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
- the edge cases that came out of this pass: a glossary term that differs only in letter case; folder names that are blank or contain a control character; revoking a share twice (audited once); a share that is already bound to one recipient; an Owner who restricts a meeting without granting themselves access and is locked out of changing it; replaying the same transcription job versus a different job.

### Is 100% coverage meaningful?

Not as a goal. 13 lines are still uncovered in the two service files. Two of them are ordinary gaps that a test could still close: renaming a glossary term successfully, and the happy path of `processing_snapshot`. The rest fall into two kinds:

- **Defensive re-raises:** for example, `except UseCaseError: if error.code == NOT_FOUND: ...; raise`. Reaching the bare `raise` needs a fake repository that throws an error the real one never throws. Such a test would check the fake, not Whadio.
- **Race guards:** for example, an access request that disappears between two reads under a row lock. Testing them properly needs two concurrent transactions. A test that fakes it reaches the line but proves nothing about the race.

Coverage says which code ran, not whether the test checked the right thing. A test without an assertion still raises coverage. In this pass, coverage was useful as a map of what nobody had tested. The value came from the assertions on refusals and edge cases. We'd rather keep the 88% with meaningful assertions than reach 100% with tests written to light up lines.

## AI Usage

The tests, the coverage runs and this document were made with Claude Code (Claude Opus 5.5); checked by Denys Zabiiaka.
