# Whadio API Quality Attributes

Targets for the Lab 4 API in `src/api/`. Each target has a number, the way it is measured, the condition under which it fails, and what in the code supports it.

## Quality Targets

| ID | Attribute | Target | Measurement | Fails if | Implementation |
| --- | --- | --- | --- | --- | --- |
| `QA-1` | Performance (time behaviour) | p95 response time ≤ 200 ms at 50 concurrent requests per endpoint | Load test each endpoint for 30 s against the local server | p95 of any endpoint exceeds 200 ms | List endpoints are paginated with `limit` capped at 100 (`core/schemas.py`); stubs answer from in-memory fixtures |
| `QA-2` | Input validation | 100% of requests with a missing, wrongly typed or out-of-range parameter are rejected with `400`/`422` and an error body naming the field | Send one invalid request per documented parameter through Swagger UI | Any invalid request returns `2xx` or `500`, or the error body does not name the field | Pydantic models with `Field` constraints on every parameter and body field; `core/errors.py` turns validation failures into `422 VALIDATION_ERROR` with `details[].field`, and invalid JSON into `400 MALFORMED_REQUEST` |
| `QA-3` | HTTP semantics | 100% of endpoints return the status codes listed in the spec: `201` on create, `204` on delete, `202` on notes regeneration, `404` for an unknown id | Call every endpoint with a valid id and an unknown id through Swagger UI | Any response code is not one documented for that endpoint | `status_code` set on each route; `error_responses()` documents every error code in the spec; one error envelope for all 4xx and 5xx |
| `QA-4` | Documentation completeness | 100% of endpoints in `openapi-generated.yaml` have a summary, a description, parameter descriptions and every error response | Review the generated spec in Swagger UI | Any endpoint or parameter is missing one of these | `summary`, `description` and `responses` on every route decorator; `description` on every `Field` |
| `QA-5` | Documentation freshness | The published spec matches the code within 10 minutes of a push to `main` | Compare the GitHub Pages spec with the spec regenerated from the latest commit | Any difference remains 10 minutes after the push | `.github/workflows/pages.yml` runs `api.openapi_export` and redeploys `docs/api/` on every push to `main` |
| `QA-6` | Confidentiality (NFR-007) | 100% of the 13 workspace, meeting, transcript and notes endpoints reject a request without a valid session | Call each of these endpoints in Swagger UI without signing in, and with a wrong `whadio_session` cookie | Any call returns data instead of `401 UNAUTHENTICATED` | `BrowserUser` / `CaptureUser` dependencies in `accounts/auth.py` on every one of these routes |

## Trade-offs

| Attribute | Trade-off | Impact | Mitigation |
| --- | --- | --- | --- |
| Input validation (`QA-2`) | Schema validation on every request adds per-request latency | Minimal: stays within the `QA-1` 200 ms budget | Constraints are declared once on Pydantic models instead of hand-written checks |
| Performance (`QA-1`) | `limit` capped at 100 items per page | Clients with large workspaces need several requests | Cursor pagination with `next_cursor` and `has_more` |
| Documentation (`QA-4` / `QA-5`) | The spec is generated from annotations, so its wording is only as good as the annotations | A missing annotation produces an incomplete spec | Caught as a `QA-4` failure in review; the spec never goes stale |
| Confidentiality (`QA-6`) | Session checks even on mock endpoints add setup now | Every call in Swagger UI needs a sign-in first | Keeps the `401` contract stable when real storage replaces the stubs; the read-only `/mcp/` stub is outside `QA-6` until personal MCP keys are implemented |

## AI Usage

This document was prepared with the assistance of Claude Code (Claude Opus 5.5). The targets derive from the non-functional requirements in [`../requirements/requirements.md`](../requirements/requirements.md) and the Lab 4 task. The authors reviewed and edited the content, and the document is reviewed through a pull request before merging.
