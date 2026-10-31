# Whadio

[![CI/CD](https://github.com/ukma-fin-ssdm-2026/Whadio/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ukma-fin-ssdm-2026/Whadio/actions/workflows/ci.yml)

Whadio is an open-source meeting recording and transcription service focused on high-quality Ukrainian and mixed Ukrainian–English speech. It records Google Meet meetings directly in the browser, generates speaker-labeled transcripts and AI notes, and provides workspaces, glossary, access control, Markdown and VTT export, and MCP integration, with privacy and self-hosting in mind.

# Members

| **Name** | **GitHub** | **Role** |
|----------|----------|----------|
| Andrii Shalaiev | @Hukyl | CI Maintainer, Requirements Lead, Architecture Lead, Backend Lead, Code Quality Lead, Integration Lead, Test Planner |
| Denys Zabiiaka  | @SquidBow | Issue Tracker Lead, Traceability Lead, Requirements-Architecture Mapper, API Quality Lead, Security Analyst, Test Lead, Quality Analyst |
| Valeriia Missirova | @v-missirova | Documentation Lead, Integration Lead, Debugging Lead, AI Code Reviewer |
| Zlata Tsepkalo | @t-zlata | Repository Maintainer, Quality Lead, Data & Threat Modeler, API Documentation Lead, Code Reviewer, Test Strategist, Review Manager, AI Code Reviewer |

# Deploying

The production stack needs a Linux host with Docker Engine and Compose v2, a DNS name that points
to the host, and a trusted TLS certificate for that name. Ports 80 and 443 must reach the host.
Clone the repository, create the configuration and place the certificate where the template
expects it:

```bash
git clone https://github.com/ukma-fin-ssdm-2026/Whadio.git
cd Whadio
cp .env.production.example .env
mkdir -p certs
cp /path/to/fullchain.pem certs/fullchain.pem
cp /path/to/privkey.pem certs/privkey.pem
```

Replace every `change-me` value and the example host name in `.env`. The default production
template runs CPU transcription and writes notes through Anthropic; the provider key and the
Hugging Face token are secrets. Generate every database, broker and storage password independently.
Then build and start the complete stack:

```bash
docker compose config --quiet
docker compose up --detach --build --wait
docker compose ps
```

`migrate` applies the database schema once. `web` and `scheduler` wait for it to succeed, and nginx
waits for `web` to become healthy. Open `https://<your-host>/`; plain HTTP redirects there. To
create the first account in the default `invite-only` mode, issue a link from the running web
container and hand it to the named recipient privately:

```bash
docker compose exec web whadio links registration --email person@example.com
```

No SMTP relay is required in `invite-only` mode. To use verified registration, uncomment and fill
the SMTP settings before changing `WHADIO_REGISTRATION_MODE=verified`. For a local Ollama model,
change the notes provider settings and add `ollama` to `COMPOSE_PROFILES`; for NVIDIA-accelerated
ASR also set `COMPOSE_FILE=compose.yaml:compose.cuda.yaml` (`;` instead of `:` on Windows). The ASR
worker otherwise uses the CPU image and does not start Ollama. Update with `git pull`, then repeat
the `docker compose up --detach --build --wait` command; volumes preserve application data.


# Development

[AGENTS.md](AGENTS.md) covers everything a contributor or their AI agent needs: the code layout,
the architecture rules, the coding standards and the checks every change must pass. In short, with
[uv](https://docs.astral.sh/uv/), Node 24 and Docker installed:

```bash
uv sync --extra asr --extra cpu  # Python 3.13, the dependencies and the dev tools, in .venv
uv run task setup                # also installs the frontend's dependencies and the git hooks
cp .env.example .env             # local credentials for the Compose stack
uv run task infra:up             # PostgreSQL, RabbitMQ, SeaweedFS and Mailpit
uv run task dev                  # the API on http://localhost:3000, with auto-reload
```

## Running the API

Database setup, migrations and integration tests are documented in
[Database implementation](docs/architecture/database.md).

The backend API lives in [`src/whadio/api/`](src/whadio/api/). It stores its data in
PostgreSQL and the recordings in SeaweedFS, and queues jobs on RabbitMQ, so start the services and
apply the migrations first: `uv run task infra:up`, then `uv run task db:upgrade`. The full design,
including what each error means, is in [`docs/api/api-design.md`](docs/api/api-design.md).
`uv run task dev` starts the API; `uv run whadio web` runs it without auto-reload.

- Swagger UI: <http://localhost:3000/api-docs> (ReDoc: <http://localhost:3000/redoc>; the
  specification: <http://localhost:3000/openapi.json>)
- Sign in with `POST /api/v1/sessions`; the browser keeps the session cookie for the other
  calls. Operator-issued links create accounts through the registration completion endpoint.
- Starting the server writes the OpenAPI specification to `docs/api/openapi-generated.yaml`
  and `.json`; to regenerate it without a server, run `uv run whadio openapi`.

## Running the web app

The React app lives in [`frontend/`](frontend/). `uv run task setup` installs its dependencies;
`uv run task frontend:install` reinstalls them from the lockfile. Start the API on port 3000 first,
then run:

```bash
cd frontend
npm run dev
```

Biome formats and lints the frontend: `npm run check` reports problems and `npm run check:fix`
fixes what it can. `npm test` runs the Vitest tests and `npm run typecheck` the TypeScript
compiler. The commit hook runs Biome whenever a commit touches `frontend/`, the push hook runs the
compiler and the tests the branch can affect, and CI runs everything.

The API's TypeScript types in `frontend/src/shared/api/schema.gen.ts` are generated from
`docs/api/openapi-generated.json` by `npm run gen:api`. The push hook regenerates them whenever
the specification or `frontend/` changes, and fails until the regenerated file is committed.

Open <http://localhost:5173>. Vite proxies `/api` requests to the local API, so browser sessions
and uploads use the backend without a separate CORS setup. Set `VITE_API_ORIGIN` (such as
`https://api.example.org`) only when the API is hosted at a different origin.

After applying the database migrations, set `WHADIO_PUBLIC_URL` to the application's public base
URL and issue the first account's registration link:

```bash
uv run whadio links registration --email person@example.com
```

The command prints a single-use link valid for 24 hours. Hand it to its intended recipient
privately; issuing another link for the same address invalidates the earlier one. Only the token's
hash is stored. An existing account is refused; use `whadio links password-reset` to recover it.

The registration page is not available yet. To redeem the link through the API, take the
registration ID from `/registrations/<id>` and the token from `#token=<token>`, then send:

```bash
curl -i -X POST 'http://localhost:3000/api/v1/registrations/<id>/complete' \
  -H 'Content-Type: application/json' \
  -d '{"token":"<token>","name":"Alice","password":"<your-password>","accept_terms":true}'
```

Replace the placeholders and use a password of 12 to 128 characters with a digit and an uppercase
letter. A successful request returns `201` and sets the browser session cookie. The scheduler
removes unused registration links once their 24-hour lifetime expires.

To make an account an administrator, grant the permission by its sign-in address, in any case:

```bash
uv run whadio admin grant --email person@example.com
```

`whadio admin revoke` takes the same option, and both commands accept `--user-id` instead. The
address must belong to an existing account. A revocation takes effect on the account's next
request; its sessions stay signed in.

An existing account can be recovered with an operator-issued reset link:

```bash
uv run whadio links password-reset --email person@example.com
```

The reset link is single-use and valid for one hour, in either registration mode. Reissuing it
invalidates the previous link. The reset page is pending the SPA milestone. To redeem the link
through the API, take the reset ID from `/password-resets/<id>` and the token from
`#token=<token>`, then send:

```bash
curl -i -X POST 'http://localhost:3000/api/v1/password-resets/<id>/complete' \
  -H 'Content-Type: application/json' \
  -d '{"token":"<token>","password":"<your-password>"}'
```

The new password follows the registration rule. A successful request ends every browser and
extension session; MCP keys keep working, and the user signs in again. Neither operator command
sends email.

`whadio dev-user` remains a local development shortcut:

```bash
uv run whadio dev-user --email margaret@whadio.dev
```

The command asks for a password without storing it in the repository and also creates the
account's personal workspace and default meeting folder.

## Running the workers

The transcription and notes workers live in [`src/whadio/workers/`](src/whadio/workers/). They
take jobs from RabbitMQ and publish their results to `processing.results`.

- `uv run task workers:up` builds the image and starts both workers in Compose; `task workers:logs`
  follows them and `task workers:down` stops them.
- The ASR worker needs `WHADIO_ASR__DIARIZATION__HF_TOKEN` in `.env`, from a Hugging Face account
  that accepted the conditions of `pyannote/speaker-diarization-community-1`.
- The notes worker refuses to start without `WHADIO_NOTES__LLM__PROVIDER`. `.env.example` sets the
  built-in model: `ollama` with `WHADIO_NOTES__LLM__MODEL=gemma4:12b-it-qat`. Run
  `uv run task llm:up` before `task workers:up`. It starts Ollama in Compose on an NVIDIA GPU (the
  NVIDIA Container Toolkit is required) at `127.0.0.1:11434` and pulls the model `.env` names into
  the `llm-models` volume; `task llm:logs` follows it. The notes worker in Compose reaches it as
  `http://llm-runtime:11434`; a worker run with `uv run whadio notes-worker` uses
  `WHADIO_NOTES__LLM__BASE_URL`, `http://localhost:11434` by default. With Ollama on a separate
  GPU host, set `OLLAMA_ADDRESS` there to its private-network address, and `LLM_RUNTIME_URL` on
  the main host to `http://<that address>:11434`. See
  [ADR-007](docs/architecture/decisions/ADR-007.md).
- Without an NVIDIA GPU, write notes with Claude instead: switch to the Anthropic lines of
  `.env.example`, with `WHADIO_NOTES__LLM__PROVIDER=anthropic`, a Claude model and
  `WHADIO_NOTES__LLM__API_KEY`. Transcripts then leave the deployment for the Anthropic API.
- The ASR worker's first start downloads its models into the `asr-models` volume, which takes a
  few minutes.
- Diarization runs on the CPU by default, which is enough for development, but transcription then
  takes about 0.7 of a recording's length, against NFR-002's 15 minutes per hour. On a machine with
  an NVIDIA GPU (driver 580 or newer and the NVIDIA Container Toolkit), add
  `COMPOSE_FILE=compose.yaml:compose.cuda.yaml` to `.env` (`;` instead of `:` on Windows) before
  `task workers:up`: the ASR worker then gets its own image, `whadio:dev-cuda`, with CUDA builds of
  torch, and diarizes on the GPU. A worker run with `uv run whadio asr-worker` needs
  `uv sync --extra asr --extra cuda` and `WHADIO_ASR__DIARIZATION__DEVICE=cuda` instead;
  `uv sync --extra asr --extra cpu` switches back.
- The ASR worker downloads recordings through presigned links signed for
  `http://seaweedfs:8333`, the name it reaches storage by in Compose.

## Connecting an AI assistant (MCP)

The server also exposes a read-only MCP endpoint at `http://localhost:3000/mcp/` with four tools:
`list_meetings`, `search_meetings`, `get_transcript` and `get_notes`. They read the meetings the
key's owner can access, and every call needs a personal MCP key as a Bearer token. A signed-in
user creates, lists and revokes keys through `/api/v1/users/me/mcp-keys`; each secret is shown
only in the creation response and is stored only as a SHA-256 hash.

- MCP Inspector: `npx @modelcontextprotocol/inspector`, choose the *Streamable HTTP* transport
  the URL `http://localhost:3000/mcp/`, and the header `Authorization: Bearer <key>`.
- Claude Code: `claude mcp add --transport http whadio http://localhost:3000/mcp/ --header
  "Authorization: Bearer <key>"`.

# Documentation

- [Team Charter](TeamCharter.md)
- [Project Description](Project-Description.md)

## Requirements Artifacts
All requirements documentation is maintained in the [`/docs/requirements/`](docs/requirements/) directory.
- [User Stories](docs/requirements/user-stories.md)
- [Requirements](docs/requirements/requirements.md)
- [Requirements Traceability Matrix (RTM)](docs/requirements/rtm.md)

## API Artifacts
All API documentation is maintained in the [`/docs/api/`](docs/api/) directory and published on
[GitHub Pages](https://ukma-fin-ssdm-2026.github.io/Whadio/).
- [API Design](docs/api/api-design.md) — resource model, conventions and design decisions
- [OpenAPI specification](docs/api/openapi-generated.yaml) — generated from the code
- [Quality Attributes](docs/api/quality-attributes.md) — measurable API quality targets with failure conditions

## Architecture Artifacts
All architecture documentation is maintained in the [`/docs/architecture/`](docs/architecture/) directory.
- [High-Level Design](docs/architecture/high-level-design.md) — overall architecture: chosen style, components, and interfaces
- [Traceability Matrix](docs/architecture/traceability-matrix.md) — requirements ↔ components, verification methods, and quality attribute scenarios
- [Data Model](docs/architecture/data-model.md)
- [Threat Model](docs/architecture/threat-model.md) — STRIDE analysis on the deployment diagram
- [UML Diagrams](docs/architecture/uml/) — in `.puml` format
- [Architecture Decision Records (ADRs)](docs/architecture/decisions/) — key architectural decisions and rationale

## Code Quality Artifacts
All code quality documentation is maintained in the [`/docs/code-quality/`](docs/code-quality/) directory.
- [Code Review Report](docs/code-quality/review-report.md) — our review of another team's code, and the feedback on ours
- [Static Analysis](docs/code-quality/static-analysis.md) — the tools, how they run, and the documented findings
- [Implementation Progress](docs/code-quality/progress.md) — the MVP's scope, status and next steps

## Testing Artifacts
Testing policy and evidence are maintained in [`/docs/testing/`](docs/testing/).
- [Testing Strategy](docs/testing/testing-strategy.md) — scope, quality goals, metrics and merge gates
- [Unit Testing and Coverage](docs/testing/testing.md) — implemented tests, edge cases and coverage results
- [Debugging Log](docs/testing/debugging-log.md) — retry-limit fault, regression tests and lessons
- [Boundary Cases](docs/testing/boundary-cases.md) — boundary value tests of the numeric and length limits
- [Coverage Report](htmlcov/index.html) — browsable line coverage for the current baseline

## AI usage
The document was prepared with the help of Claude Code (Claude Opus 5 model) and OpenAI Codex based on the team's decisions; the content was manually checked and edited, and the document is reviewed via a pull request before merging.
