# Whadio

[![CI/CD](https://github.com/ukma-fin-ssdm-2026/Whadio/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ukma-fin-ssdm-2026/Whadio/actions/workflows/ci.yml)

Whadio is an open-source meeting recording and transcription service focused on high-quality Ukrainian and mixed Ukrainian–English speech. It records Google Meet meetings directly in the browser, generates speaker-labeled transcripts and AI notes, and provides workspaces, glossary, access control, Markdown and VTT export, and MCP integration, with privacy and self-hosting in mind.

# Members

| **Name** | **GitHub** | **Role** |
|----------|----------|----------|
| Andrii Shalaiev | @Hukyl | CI Maintainer, Requirements Lead, Architecture Lead, Backend Lead |
| Denys Zabiiaka  | @SquidBow | Issue Tracker Lead, Traceability Lead, Requirements-Architecture Mapper, API Quality Lead |
| Valeriia Missirova | @v-missirova | Documentation Lead, Integration Lead |
| Zlata Tsepkalo | @t-zlata | Repository Maintainer, Quality Lead, Data & Threat Modeler, API Documentation Lead |


# Development

[AGENTS.md](AGENTS.md) covers everything a contributor or their AI agent needs: the code layout,
the architecture rules, the coding standards and the checks every change must pass. In short, with
[uv](https://docs.astral.sh/uv/) and Docker installed:

```bash
uv sync --extra asr --extra cpu  # Python 3.13, the dependencies and the dev tools, in .venv
uv run task setup                # also installs the git hooks
cp .env.example .env             # local credentials for the Compose stack
uv run task infra:up             # PostgreSQL, RabbitMQ, SeaweedFS and Mailpit
uv run task dev                  # the API on http://localhost:3000, with auto-reload
```

## Running the API

The backend API lives in [`src/whadio/api/`](src/whadio/api/). It is a stub: it implements 16
of the 70 designed operations, answers with fixed demo data and stores nothing. The full design,
including what each error means, is in [`docs/api/api-design.md`](docs/api/api-design.md).
`uv run task dev` starts it; `uv run whadio web` runs it without auto-reload.

- Swagger UI: <http://localhost:3000/api-docs> (ReDoc: <http://localhost:3000/redoc>; the
  specification: <http://localhost:3000/openapi.json>)
- Sign in with `POST /api/v1/sessions` as `alice@whadio.dev` with the password
  `whadio-demo-pass`; the browser keeps the session cookie for the other calls. The demo ids
  are listed at the top of the Swagger page.
- Starting the server writes the OpenAPI specification to `docs/api/openapi-generated.yaml`
  and `.json`; to regenerate it without a server, run `uv run whadio openapi`.

## Running the workers

The transcription and notes workers live in [`src/whadio/workers/`](src/whadio/workers/). They
take jobs from RabbitMQ and publish their results to `processing.results`.

- `uv run task workers:up` builds the image and starts both workers in Compose; `task workers:logs`
  follows them and `task workers:down` stops them.
- In `.env`, the notes worker needs `WHADIO_NOTES__API_KEY` (Anthropic). The ASR worker needs
  `WHADIO_ASR__DIARIZATION__HF_TOKEN` from a Hugging Face account that accepted the conditions of
  `pyannote/speaker-diarization-community-1`.
- The ASR worker's first start downloads its models into the `asr-models` volume, which takes a
  few minutes.
- The ASR worker downloads recordings through presigned links signed for
  `http://seaweedfs:8333`, the name it reaches storage by in Compose.

## Connecting an AI assistant (MCP)

The server also exposes a read-only MCP endpoint at `http://localhost:3000/mcp/` with four tools:
`list_meetings`, `search_meetings`, `get_transcript` and `get_notes`. They read the same demo
data as the REST stubs. The stub needs no key; personal MCP keys are designed but not
implemented yet.

- MCP Inspector: `npx @modelcontextprotocol/inspector`, choose the *Streamable HTTP* transport
  and the URL `http://localhost:3000/mcp/`.
- Claude Code: `claude mcp add --transport http whadio http://localhost:3000/mcp/`.

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

## AI usage
The document was prepared with the help of Claude Code (Claude Opus 5 model) based on the team's decisions; the content was manually checked and edited, and the document is reviewed via a pull request before merging.
