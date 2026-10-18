# AGENTS.md

How to work in this repository. It applies to people and AI coding agents alike; `CLAUDE.md`
imports it. The commit hooks and CI enforce most of it, and reviewers check the rest.

## The project

Whadio is an open-source, self-hostable service that records Google Meet calls, transcribes them
with speaker separation and writes notes with an LLM. Read the document that governs a change
before making it:

| Changing | Read first |
|---|---|
| Behaviour users see | `docs/requirements/requirements.md`, `docs/requirements/user-stories.md` |
| Where code goes and what may call what | `docs/architecture/high-level-design.md`, `docs/architecture/uml/component-diagram.puml`, `docs/architecture/decisions/` |
| Tables and their integrity rules | `docs/architecture/data-model.md` |
| Authentication, tokens, meeting content or logs | `docs/architecture/threat-model.md` |
| The HTTP API | `docs/api/api-design.md` |

When the code and these documents disagree, stop and ask instead of picking one.

## Layout

```text
src/whadio/
  migrations/     packaged Alembic revisions and database integrity guards
  cli.py          the `whadio` command: `web`, `openapi`; the workers and the scheduler add theirs
  api/            the `web` runtime: FastAPI app, one subpackage of routes per module, MCP server
  scheduler/      the `scheduler` runtime: periodic jobs
  workers/asr/    the transcription worker (GPU host)
  workers/notes/  the notes worker
  contracts/      job messages and queue names, shared by Processing and the workers
  shared/         framework-free utilities any runtime may use: settings, logging, clients
  <module>/       one package per backend module of the high-level design, listed below
frontend/         the web SPA, with its own toolchain
infra/            configuration that compose.yaml mounts into the services
```

| Package | Module | MVP owner |
|---|---|---|
| `accounts` | Accounts & Workspaces | Denys |
| `access_policy` | Access Policy | Valeriia |
| `meetings` | Meetings | Valeriia |
| `processing` | Processing | Denys |
| `audit` | Audit | Denys |
| `retention` | Retention | Valeriia |
| `capture` | Capture: the recording upload | Denys |
| `export`, `notifications`, `admin` | Export, Notifications, Admin & Monitoring | after the MVP |
| `contracts`, `workers` | Job contracts, Transcription and Notes pipelines | Andrii, Zlata |
| `frontend/` | Web SPA | Zlata |

Valeriia owns the database: the schema, migrations and indexes. A module's owner also owns its
routes in `api/<module>/`.

### Inside a module

A module holds domain logic and persistence, and nothing about HTTP:

- `models.py`: the tables the module owns; no other module reads or writes them directly.
- `repositories.py`: persistence behind a Protocol, such as `IMeetingRepository`.
- `services.py`: the use cases, which the runtimes and other modules call.
- `settings.py`: the module's configuration, if it has any.
- `test_<file>.py`: tests, next to the file they test.

Turn a file into a subpackage of the same name when it grows. Routes in `api/<module>/` call the
module's services and only translate between HTTP and the service.

### Dependency rules

import-linter checks these on every commit (`[tool.importlinter]` in `pyproject.toml`):

1. A module calls only the modules below it in the component diagram:
   `capture | export | admin | retention` → `processing` → `meetings` → `access_policy` →
   `accounts` → `notifications | audit`. To call upwards, declare a Protocol in the lower module,
   implement it in the higher one and connect the two in the runtime's composition root.
2. Modules never import `api`, `scheduler`, `workers` or `cli`.
3. Only `api` and `cli` import FastAPI, Starlette, FastMCP, MCP or uvicorn.
4. Workers never import backend modules, and the runtimes never import each other.
5. `contracts` and `shared` import no other Whadio package.
6. Only `processing` and `workers` import `contracts`.

These rules are the architecture. Changing one needs the architecture lead's agreement and an
update of the high-level design in the same pull request.

## Setup

You need uv 0.11.16 or newer, Docker with Compose v2, and git. Every tool, Task included, installs
into `.venv`; never install project tools globally.

```bash
uv sync --extra asr --extra cpu  # Python 3.13, the dependencies and the dev tools, in .venv
uv run task setup                # also installs the git hooks
cp .env.example .env             # local credentials for the Compose stack
uv run task infra:up             # PostgreSQL, RabbitMQ, SeaweedFS and Mailpit
uv run task dev                  # the API with auto-reload
```

`uv run task --list` shows every task. Local addresses, with credentials in `.env`:

| Service | Address |
|---|---|
| API | <http://localhost:3000/api-docs> |
| PostgreSQL | `localhost:5432`, database `whadio`: `whadio_owner` runs migrations, `whadio_app` serves the app |
| RabbitMQ | `amqp://localhost:5672/whadio`, management UI <http://localhost:15672> |
| S3 (SeaweedFS) | <http://localhost:8333>, bucket `recordings` |
| Mailpit | SMTP `localhost:1025`, UI <http://localhost:8025> |

If a port is taken on your machine, set the matching `*_PORT` variable in `.env`.

`uv run task workers:up` builds the image and starts the notes and ASR workers in Compose, with
the keys described in `.env.example`. The ASR worker reaches storage as `seaweedfs:8333`, so its
presigned links are signed for `http://seaweedfs:8333`.

## Verifying a change

A change is done when `uv run task check` and `uv run task test` pass and a teammate has approved
the pull request. The commit hook runs the same checks as `task check`, in this order, and stops at
the first failure: branch name, file hygiene, gitleaks, `uv lock --check`, `ruff check --fix` and
`ruff format` on the whole project, the suppression ban, typos, schema and workflow checks,
import-linter, ty, basedpyright, Bandit, deptry, the OpenAPI drift check and the fast tests. The
commit message is checked last. `git push` runs the whole test suite. CI repeats all of this but
the branch name, and adds `uv run task audit`: uv audit and a gitleaks scan of the whole history.
On a pull request, CI checks the title and every commit message against the commit format.

- Never bypass the checks: no `--no-verify`, no `SKIP=`. If a check is wrong, fix it in its own
  pull request.
- Never add an inline suppression: `# type: ignore`, `# pyright: ignore`, `# ty: ignore`,
  `# noqa` and `# nosec` are refused. Fix the code. A genuine false positive gets a scoped
  exception in `pyproject.toml` with a one-line reason, and the pull request explains it.
- When a hook changes files (ruff, whitespace, the OpenAPI specification), review the change, stage
  it and commit again.
- Ruff's fixes conflict with a partly staged file: run `uv run task fix` and stage the whole file.
- Changing a route or a schema regenerates `docs/api/openapi-generated.*`; commit them with it.

## Code standards

Python, beyond what ruff enforces:

- **Types.** Strict, with no escape hatches: no `Any`, `cast` or `object` to quiet the checker.
  Validate untrusted data (request bodies, messages, the environment) at the boundary with
  pydantic, and pass typed values inwards.
- **Interfaces.** `typing.Protocol`, named with an `I` prefix (`IMeetingRepository`), not ABCs.
  Prefer composition to inheritance.
- **Dependencies.** Pass collaborators through constructors. Each runtime wires its objects in one
  composition root (FastAPI dependencies in `api/`). No module-level singletons or mutable
  globals.
- **Imports.** Relative inside `whadio` (`from ..meetings.services import ...`); absolute for the
  standard library and third-party packages.
- **Models.** Every pydantic field has `Field(description=...)`, which reaches the OpenAPI
  specification. API requests extend `Input` and responses `Output` (`api/core/schemas.py`); API
  errors are raised as `ApiError` and leave as the error envelope.
- **Settings.** pydantic-settings with the `WHADIO_` prefix, read from the environment and `.env`.
  Add every new variable to `.env.example`.
- **Security.** Store tokens and keys only hashed or encrypted, and read secrets from the
  environment. Never log transcript or note text, recordings, tokens or keys (threat model,
  "Design Constraints Derived From This Model").
- **Comments.** Write one only when a competent reader could otherwise make a wrong edit: an
  external library's quirk, an invariant the types cannot express, a deliberate deviation, or
  provenance. Never restate the code. Section banners take one line: `# --- Upload validation ---`.
  Docstrings only where they state a contract.

Tests use pytest:

- They sit next to the code: `meetings/test_services.py` tests `meetings/services.py`.
- The name states the behaviour: `test_restricted_meeting_is_missing_for_other_members`.
- The body is marked `# Arrange`, `# Act`, `# Assert`, and nothing else in it is commented.
- One logical assertion per test. Cover edge cases, refusals and validation errors, not only the
  happy path.
- Mark a test that needs running services or models `@pytest.mark.slow`: the commit hook skips it;
  the push hook and CI run it.

## Git and pull requests

- Branch from `main` as `<type>/#<issue>-<short-description>`, such as
  `feat/#61-meeting-repository`.
- Commit as `<type>(#<issue>): <subject>`, with the type one of `build`, `chore`, `ci`, `docs`,
  `feat`, `fix`, `perf`, `refactor`, `revert`, `style`, `test`, and the subject in the imperative.
- Dependabot is the one exception: its branches are named `dependabot/...`, its commits and pull
  request titles start with `build(deps):` or `build(deps-dev):`, and its pull requests reference
  no issue.
- One concern per commit; never mix formatting with behaviour.
- A pull request references its issue, needs one teammate's approval and follows the review rules
  in `TeamCharter.md`, section 11. Its title follows the commit format, since a squash merge uses it.
- Disclose AI use: an "AI Usage" section in documents, and the tool named in review summaries
  (`TeamCharter.md`, section 9).

## Ask before you

- push to `main`, force-push a shared branch or merge a pull request;
- change the import-linter contracts, the hooks, CI or the tool configuration in `pyproject.toml`;
- run `uv run task infra:reset`, which deletes the local database, broker and storage data;
- commit `.env`, credentials, recordings or model weights;
- install anything outside `.venv`; add dependencies with `uv add`, and tools with `uv add --dev`.
