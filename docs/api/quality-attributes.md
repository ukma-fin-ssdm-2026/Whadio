# Whadio API Quality Attributes

Targets for the Lab 4 API in `src/whadio/api/`. Each target has a number, the way it is measured, the condition under which it fails, and what in the code supports it.

## Priorities

Whadio stores recordings, transcripts and notes of private meetings, so confidentiality of that content is the critical attribute: when it conflicts with convenience or raw speed, confidentiality wins. Correct input handling comes next, because every later layer trusts what the API accepted. Performance only has to stay within the page-load budget of NFR-001; we deliberately give up more helpful error messages (a hidden resource is `404`, not `403`) and some latency (validation and session checks on every request) for the first two.

## Quality Targets

| ID | Attribute | Target | Measurement | Fails if | Implementation |
| --- | --- | --- | --- | --- | --- |
| `QA-1` | Performance (time behaviour, NFR-001) | p95 response time ≤ 200 ms at 50 concurrent requests per endpoint; the 200 ms is the API's share of NFR-001's 2 s page-load budget | k6, 50 virtual users for 30 s per endpoint, against one uvicorn worker on a team member's laptop; covers every endpoint except the recording upload, whose time depends on the file size | p95 of any measured endpoint exceeds 200 ms | Database-backed list endpoints use keyset pagination with `limit` capped at 100 (`core/schemas.py`) |
| `QA-2` | Input validation | 100% of requests with a missing, wrongly typed or out-of-range parameter are rejected with `400`, `413`, `415` or `422`; a `422 VALIDATION_ERROR` body names each offending field | For every parameter and body field, send one request each with the value missing (if required), of the wrong type, and out of range (if constrained); body fields through Swagger UI, query parameters with curl, because Swagger UI refuses out-of-range values before sending them | Any invalid request returns `2xx` or `5xx`, or a `422` body does not name the field | Pydantic models with `Field` constraints on every parameter and body field; `core/errors.py` turns validation failures into `422 VALIDATION_ERROR` with `details[].field`, and invalid JSON into `400 MALFORMED_REQUEST`; the upload size check in `meetings/routes.py` returns `413`, and `meetings/audio.py` (#51) returns `415` unless the file decodes as a supported audio format |
| `QA-3` | HTTP semantics | 100% of endpoints return the status codes listed in the spec: `201` on create, `204` on delete, `202` on asynchronous work, `404` for an unknown id | Through Swagger UI, one request per documented response code of every endpoint; `413` with curl, uploading a sparse file over 500 MiB (`truncate -s 501M big.mp3`); `429` through the nginx rate limit | Any response code is not the one documented for that request | `status_code` set on each route; `error_responses()` documents every error code in the spec; one error envelope for all 4xx and 5xx |
| `QA-4` | Documentation completeness | 100% of endpoints in `openapi-generated.yaml` have a summary, a description, parameter descriptions and every error response | Redocly CLI lint step in CI (`redocly lint docs/api/openapi-generated.yaml`) | Any endpoint or parameter is missing one of these | `summary`, `description` and `responses` on every route decorator; `description` on every `Field`; enforced in CI by Redocly CLI (`redocly.yaml`) |
| `QA-5` | Documentation freshness | The published spec matches the code within 10 minutes of a push to `main` | Compare the GitHub Pages spec with the spec regenerated from the latest commit | Any difference remains 10 minutes after the push | In `.github/workflows/ci.yml`, `task check` runs the `openapi` hook (`whadio openapi`), which fails the `verify` job when the committed spec differs from the code; on every push to `main` that passes `verify`, the `deploy` job republishes `docs/api/` |
| `QA-6` | Authenticity (NFR-012) | 100% of the 13 workspace, meeting, transcript and notes endpoints reject a request without a valid session | Call each of these endpoints in Swagger UI without signing in, and with a wrong `whadio_session` cookie | Any call returns data instead of `401 UNAUTHENTICATED` | `BrowserUser` / `CaptureUser` dependencies in `accounts/auth.py` on every one of these routes |

## Trade-offs

| Attribute | Trade-off | Impact | Mitigation |
| --- | --- | --- | --- |
| Input validation (`QA-2`) | Schema validation on every request adds per-request latency | Minimal: stays within the `QA-1` 200 ms budget | Accepted: `QA-1` leaves headroom for it |
| Performance (`QA-1`) | `limit` capped at 100 items per page | Clients with large workspaces need several requests | Cursor pagination with `next_cursor` and `has_more` |
| Confidentiality vs. usability | A resource the caller cannot see is `404`, never `403` | Clients cannot tell a missing resource from a hidden one, so errors are less helpful | Hiding whether a meeting exists matters more; `403` is kept for resources the caller can see but whose action their role does not allow |
| Authenticity (`QA-6`) | Session checks on every protected endpoint add work to each request | Every protected call in Swagger UI needs a sign-in first | Keeps the `401` contract consistent across resources |

## Known Gaps

- **Authorization (NFR-007):** stored workspace roles, meeting restrictions and sharing decisions are enforced across the API, recording, export and MCP paths. The remaining gap is a single system-level authorization-matrix run against the deployed stack.
- **MCP (NFR-009):** the read-only `/mcp/` endpoint requires a personal MCP key, stored hashed, and applies the same meeting access policy as HTTP. Authentication rate limiting remains a tracked security follow-up.
- **Availability (reliability):** there is no measured availability target because no public instance is deployed yet. Once deployed, `/health` supports the target "availability ≥ 99% per week, polled every minute; fails above 100 minutes of total downtime in 7 days".

## AI Usage

This document was prepared with the assistance of Claude Code (Claude Opus 5.5). The targets derive from the non-functional requirements in [`../requirements/requirements.md`](../requirements/requirements.md) and the Lab 4 task. The authors reviewed and edited the content, and the document is reviewed through a pull request before merging.
