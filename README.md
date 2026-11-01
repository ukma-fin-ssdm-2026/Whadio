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
sudo chown 101:101 certs/privkey.pem
sudo chmod 600 certs/privkey.pem
```

Replace every `change-me` value and the example host name in `.env`. The default production
template runs CPU transcription and writes notes through Anthropic; the provider key and the
Hugging Face token are secrets. Generate every database, broker and storage password independently
with `openssl rand -hex 32`; broker passwords must be URL-safe because they are embedded in AMQP
URLs. The nginx image runs as uid 101, so the private key stays owner-readable only after the
ownership change above. Then build and start the complete stack:

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

After the recipient completes that link, grant the first account administrator access:

```bash
docker compose exec web whadio admin grant --email person@example.com
```

No SMTP relay is required in `invite-only` mode. To use verified registration, uncomment and fill
the SMTP settings before changing `WHADIO_REGISTRATION_MODE=verified`. For a local Ollama model,
change the notes provider settings and add `ollama` to `COMPOSE_PROFILES`; for NVIDIA-accelerated
ASR also set `COMPOSE_FILE=compose.yaml:compose.cuda.yaml` (`;` instead of `:` on Windows). The ASR
worker otherwise uses the CPU image and does not start Ollama. Update with `git pull`, then repeat
the `docker compose up --detach --build --wait` command; volumes preserve application data.

The template starts the bundled SeaweedFS through the `storage` profile. To use AWS S3 or another
S3-compatible service, remove `storage` from `COMPOSE_PROFILES`, set
`WHADIO_STORAGE__ENDPOINT_URL` and the storage credentials (plus region and bucket when needed),
and leave `WHADIO_STORAGE__PUBLIC_ENDPOINT_URL` unset so presigned playback links point directly
to that HTTPS endpoint.


# Development

[AGENTS.md](AGENTS.md) covers everything a contributor or their AI agent needs: the code layout,
the architecture rules, the coding standards and the checks every change must pass. In short, with
[uv](https://docs.astral.sh/uv/), Node 24 and Docker installed, this sequence takes a fresh clone
to the first local sign-in:

```bash
git clone https://github.com/ukma-fin-ssdm-2026/Whadio.git
cd Whadio
uv sync --extra asr --extra cpu  # Python 3.13, the dependencies and the dev tools, in .venv
uv run task setup                # also installs the frontend's dependencies and the git hooks
cp .env.example .env             # local credentials for the Compose stack
uv run task infra:up             # PostgreSQL, RabbitMQ, SeaweedFS and Mailpit
uv run task db:upgrade           # apply the database schema
uv run whadio dev-user --email person@example.com
```

`dev-user` asks for the local password without writing it to the repository. Keep the
infrastructure running, then start the API and SPA in separate terminals:

```bash
uv run task dev                  # terminal 1: API on http://localhost:3000
npm --prefix frontend run dev    # terminal 2: SPA on http://localhost:5173
```

Open <http://localhost:5173> and sign in with `person@example.com` and the password entered above.
To process uploaded recordings as well, configure the model credentials described in
[Running the workers](#running-the-workers), then run `uv run task workers:up` in another terminal.

Before playing a recording locally, map `seaweedfs` to `127.0.0.1` in the system hosts file
(`/etc/hosts` on Linux and macOS, or `C:\Windows\System32\drivers\etc\hosts` on Windows). The
browser then resolves the same storage host used to sign links for the Compose ASR worker.

## Try Whadio

There is no public evaluation instance yet. To try the current product locally, follow the setup
above. The dedicated midterm demo is tracked in
[#192](https://github.com/ukma-fin-ssdm-2026/Whadio/issues/192); the available per-lab walkthroughs
are linked in the [labs index](#labs-index).

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
compiler and the tests the branch can affect, and CI runs everything. The
[testing guide](docs/testing/testing.md#4-frontend-tests) describes the tests.

Styling is MUI only: the theme in `frontend/src/app/theme/` sets the colours and component
defaults, and components add the rest with `sx`. There is no stylesheet.

The API's TypeScript types in `frontend/src/shared/api/schema.gen.ts` are generated from
`docs/api/openapi-generated.json` by `npm run gen:api`. The push hook regenerates them whenever
the specification or `frontend/` changes, and fails until the regenerated file is committed.

Each file in `frontend/src/routes/` is a page, and `frontend/src/routeTree.gen.ts` is generated
from them and committed. Vite regenerates it while it runs, and `npm run gen:routes` does so
without a server, both with the options in `frontend/tsr.config.json`. The push hook and
`uv run task check` regenerate it whenever `frontend/` changes, and fail until the regenerated
file is committed.

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

## Installing the Chrome extension

The extension in [`extension/`](extension/) records a Google Meet call, the other participants
and your microphone, and uploads it to a Whadio server. You need desktop Chrome 116 or newer, a
Whadio server it can reach (`https://`, or `http://localhost` and `http://127.0.0.1`), and a
Meet call with at least one other participant.

1. Get the extension. Open the latest passing CI run on `main` under Actions and download its
   `whadio-extension-<version>.zip` artifact, then unzip it into a folder. Downloading needs a
   GitHub sign-in, and artifacts expire after 30 days. To build the archive yourself, run
   `uv run --no-project python -I .github/scripts/package_extension.py extension .`; to try your
   own changes, load `extension/` itself.
2. Open `chrome://extensions`, turn on Developer mode, choose Load unpacked and pick the folder.
3. Click Whadio in the toolbar, enter the server address and sign in with your Whadio account.
   Choose the folder recordings go to.
4. Join the call, open the popup, confirm that everyone agreed to be recorded and press Start
   recording. Alt+Shift+R starts and stops a recording too, but it reads the consent box on the
   card in the Meet page, not the popup's: if that box isn't ticked, the first press shows the
   card and asks you to tick it.
5. The first time, nothing is recorded yet: Whadio opens a tab that asks for your microphone.
   Allow it, close that tab and press Start recording again. Chrome remembers the choice, so later
   recordings start at once.
6. Stop from the popup. The meeting appears in the web app; it's transcribed and gets notes once
   the [workers](#running-the-workers) are running. If the upload fails, the extension saves the
   recording as a `.webm` file in your downloads instead.

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

## Requirements Artifacts (Артефакти вимог)
All requirements documentation is maintained in the [`/docs/requirements/`](docs/requirements/) directory.
- [Proposal mini-specification](Project-Description.md#mini-technical-specification) — goal,
  functions, quality requirements and constraints from the proposal stage
- [User Stories](docs/requirements/user-stories.md)
- [Requirements](docs/requirements/requirements.md)
- [Requirements Traceability Matrix (RTM)](docs/requirements/rtm.md)

## API Artifacts
All API documentation is maintained in the [`/docs/api/`](docs/api/) directory and published on
[GitHub Pages](https://ukma-fin-ssdm-2026.github.io/Whadio/).
- [API Design](docs/api/api-design.md) — resource model, conventions and design decisions
- [OpenAPI specification](docs/api/openapi-generated.yaml) — generated from the code
- [OpenAPI JSON](docs/api/openapi-generated.json) and its [browser viewer](docs/api/index.html)
- [Quality Attributes](docs/api/quality-attributes.md) — measurable API quality targets with failure conditions

## Architecture Artifacts
All architecture documentation is maintained in the [`/docs/architecture/`](docs/architecture/) directory.
- [High-Level Design](docs/architecture/high-level-design.md) — overall architecture: chosen style, components, and interfaces
- [Traceability Matrix](docs/architecture/traceability-matrix.md) — requirements ↔ components, verification methods, and quality attribute scenarios
- [Database implementation](docs/architecture/database.md)
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
- [Test Doubles](docs/testing/test-doubles.md) — doubles used at each test boundary
- [Coverage Report](htmlcov/index.html) — browsable line coverage for the current baseline

## Validation Artifacts

Validation evidence is maintained in [`/docs/validation/`](docs/validation/).

- [Test Plan](docs/validation/test-plan.md) — planned and executed cases with measured results
- [Review Log](docs/validation/review-log.md) — requirements and test-plan review findings

## Labs Index

| Lab | Artifacts | Video links |
|---|---|---|
| 1 — Proposal | [Project description](Project-Description.md), [Team Charter](TeamCharter.md) | [Andrii](Labs/Lab01/video_Andrii.txt), [Denys](Labs/Lab01/video_Denys.txt), [Valeriia](Labs/Lab01/video_Valeriia.txt), [Zlata](Labs/Lab01/video_Zlata.txt) |
| 2 — Requirements | [User stories](docs/requirements/user-stories.md), [requirements](docs/requirements/requirements.md), [RTM](docs/requirements/rtm.md) | [Andrii](Labs/Lab02/video_Andrii.txt), [Denys](Labs/Lab02/video_Denys.txt), [Valeriia](Labs/Lab02/video_Valeriia.txt), [Zlata](Labs/Lab02/video_Zlata.txt) |
| 3 — API | [API design](docs/api/api-design.md), [OpenAPI](docs/api/openapi-generated.yaml), [quality attributes](docs/api/quality-attributes.md) | [Andrii](Labs/Lab03/video_Andrii.txt), [Denys](Labs/Lab03/video_Denys.txt), [Valeriia](Labs/Lab03/video_Valeriia.txt), [Zlata](Labs/Lab03/video_Zlata.txt) |
| 4 — Database | [Data model](docs/architecture/data-model.md), [database implementation](docs/architecture/database.md), [ER diagram](docs/architecture/uml/er-model.svg) | [Andrii](Labs/Lab04/video_Andrii.txt), [Denys](Labs/Lab04/video_Denys.txt), [Valeriia](Labs/Lab04/video_Valeriia.txt), [Zlata](Labs/Lab04/video_Zlata.txt) |
| 5 — Architecture | [HLD](docs/architecture/high-level-design.md), [architecture traceability](docs/architecture/traceability-matrix.md), [threat model](docs/architecture/threat-model.md), [UML](docs/architecture/uml/), [ADRs](docs/architecture/decisions/) | [Andrii](Labs/Lab05/video_Andrii.txt), [Denys](Labs/Lab05/video_Denys.txt), [Valeriia](Labs/Lab05/video_Valeriia.txt), [Zlata](Labs/Lab05/video_Zlata.txt) |
| 6 — Implementation quality | [Progress](docs/code-quality/progress.md), [static analysis](docs/code-quality/static-analysis.md), [review report](docs/code-quality/review-report.md), [coverage](htmlcov/index.html) | [Andrii](Labs/Lab06/video_Andrii.txt), [Denys](Labs/Lab06/video_Denys.txt), [Valeriia](Labs/Lab06/video_Valeriia.txt), [Zlata](Labs/Lab06/video_Zlata.txt) |
| 7 — Verification and validation | [Testing strategy](docs/testing/testing-strategy.md), [testing and coverage](docs/testing/testing.md), [boundary cases](docs/testing/boundary-cases.md), [debugging log](docs/testing/debugging-log.md), [test plan](docs/validation/test-plan.md), [review log](docs/validation/review-log.md) | [Andrii](Labs/Lab07/video_Andrii.txt), [Denys](Labs/Lab07/video_Denys.txt), [Valeriia](Labs/Lab07/video_Valeriia.txt), [Zlata](Labs/Lab07/video_Zlata.txt) |

## AI usage
The document was prepared with the help of Claude Code (Claude Opus 5 model) and OpenAI Codex based on the team's decisions; the content was manually checked and edited, and the document is reviewed via a pull request before merging.
