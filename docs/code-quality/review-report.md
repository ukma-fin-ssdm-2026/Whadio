# Review: Waterfall

Team's repository URL: <https://github.com/ukma-fin-ssdm-2026/waterfall/tree/main>
Reviewed commit SHA: `ee2c003582951b07d7e12e453d7739e03c35b619`.

## Strong sides

1. Consistent error contracts - the team is using a single error model for all errors.

2. Detailed input data validation (e.g., URL validation).

3. Correct REST semantics: versioning, Guid, Location header, etc.

## Improvement sides

1. The service layer is absent, thus the business logic (despite being small right now) is kept directly in the controllers. Suggestion: move the business logic into respective separate services, which will be consolidating repository interactions and other business logic; respectively, the handlers will call the services to perform the actions, thus separating the framework from the business logic.

2. Too many comments, which often repeat the code itself; even the models have redundant comments. In our opinion, there is no need for such extensive comments, apart from the obvious (the REST codes specification, which looks clearly like an OpenAPI spec) and non-obvious (due to lack of our knowledge of the C# framework). Additionally, comments in Ukrainian are present, while all of the comments in the MCP module are in English.

3. Absence of tests and static analysis.

## Potential vulnerabilities and risks

Absence of authentication, making each endpoint accessible to everybody. We suspect that this just wasn't developed under Lab04, and will be implemented later in Lab05.


No AI was used when writing the above portion of the file.

## AI Review

Was done by: Claude Code (Opus 5.5@xhigh).

<details>

<summary>Raw AI output</summary>

### Strengths
1. **Thin controllers behind repository interfaces, with one error contract** — Controllers only handle HTTP concerns. They take `IVacancyRepository` / `ISavedVacancyRepository` through constructor injection (`src/api/Controllers/VacanciesController.cs:22-26`, `src/api/Controllers/SavedVacanciesController.cs:24-32`), and the implementations are registered in one place (`src/api/Program.cs:77-78`). Swapping the in-memory stub for EF Core later should touch only the `Services` layer. Error responses all come from one factory, `ApiErrorResponse.Create` (`src/api/Models/Common/ApiErrorResponse.cs:14-32`), through shared helpers `ErrorNotFound` / `ErrorBadRequest` / `ErrorConflict` in `src/api/Controllers/ApiControllerBase.cs:46-94`. So every 4xx has the same `code` / `message` / `request_id` / `details` shape, and no action builds error JSON by hand. All repository methods are async and pass a `CancellationToken` through (`src/api/Services/IVacancyRepository.cs:10-14`), so the contract is ready for a real database.

2. **Input validation is declared on the models and checked before any action runs** — Request models state their limits with DataAnnotations: required fields, length ranges, ISO-3 currency, `[Url]` on `source_url`, and salary ranges (`src/api/Models/Vacancies/CreateVacancyRequest.cs:16-17, 85, 101, 117-118`). Rules that span two fields use `IValidatableObject`, for example `salary_min <= salary_max` (`CreateVacancyRequest.cs:129-137`, `src/api/Models/Vacancies/VacancyFilterParameters.cs:75-83`). Paging is capped server-side with `page_size` limited to 1-100 (`VacancyFilterParameters.cs:24-26`), which bounds the cost of each list query. Every id route uses a `{id:guid}` constraint (`VacanciesController.cs:63, 121, 154`), so a malformed id never reaches the code. Error messages name the JSON field (`title`, `source_url`), not the C# property.

3. **XML documentation is wired into the published API spec** — `GenerateDocumentationFile` is on (`src/api/Waterfall.Api.csproj:7`), and the XML file is passed to Swagger (`src/api/Program.cs:105-111`). Actions document `<summary>`, `<remarks>`, `<param>` and every `<response code>` (`VacanciesController.cs:28-38`), and these match the `[ProducesResponseType]` attributes (`VacanciesController.cs:45-46`). DTO properties carry `<example>` values (`src/api/Models/Vacancies/VacancyDto.cs:11-16`). `OpenApiGenerator` (`src/api/Services/OpenApiGenerator.cs:14-28`) regenerates `docs/api/openapi-generated.yaml` from that code, and only writes it when the content changed. That keeps the committed spec in step with the implementation.

### Improvements
1. **The validation-error pipeline has a crash path and unreachable duplicate checks** — `InvalidModelStateResponseFactory` (`src/api/Program.cs:19-73`) has three problems:
   - **Crash on an empty key.** It computes the field name as `char.ToLowerInvariant(key[0]) + key[1..]` (`Program.cs:44`). When a `[FromBody]` request arrives with an empty body, ASP.NET Core records "A non-empty request body is required" under the empty key `""`. `key[0]` then throws `IndexOutOfRangeException`. For example, `POST /api/v1/vacancies` with `Content-Type: application/json` and no body returns a 500 instead of the documented 400.
   - **`provided_value` is always null for JSON.** The value is looked up only in `Request.Form` / `Request.Query` (`Program.cs:36-38`). All write endpoints take JSON bodies, so nothing is ever found.
   - **Unreachable checks.** Because of `[ApiController]` (`ApiControllerBase.cs:9`), this factory runs before any action. So the `if (!ModelState.IsValid)` blocks in `VacanciesController.cs:99-102, 132-135` and `SavedVacanciesController.cs:101-104` never execute. They still look like the place where validation happens.

   Request-ID resolution is also written three times with different precedence (`Program.cs:59-61`, `Program.cs:119-123`, `ApiControllerBase.cs:19-36`). The middleware always sets `X-Correlation-Id`, so the `X-Request-Id` and `TraceIdentifier` branches in the base class never run either.

   *Suggestion:* move the factory into its own class (e.g. `Infrastructure/ValidationErrorResponseFactory.cs`). Map an empty key to a name such as `"body"`, strip the `$.` JSON-path prefix, and take the value from `ModelStateEntry.AttemptedValue` instead of re-reading Form/Query. Delete the dead `ModelState.IsValid` blocks. Resolve the request ID once in the middleware, store it in `HttpContext.Items`, and read it from there. Add an integration test for the empty-body case.

2. **`SavedVacancyRepository` quietly treats an id as either kind of key, and its logic is spread across layers** — `GetByIdAsync` and `DeleteAsync` first look up the bookmark id. If that fails, they search by `VacancyId` instead (`src/api/Services/SavedVacancyRepository.cs:54-57, 100-105`). The documented contract says `{id}` is the saved-record id (`SavedVacanciesController.cs:56, 129`, and the generated OpenAPI). So `GET` and `DELETE /api/v1/saved-vacancies/{vacancyId}` succeed when the docs promise a 404. Clients can come to depend on this undocumented behaviour, and the data layer is making an API-level decision.

   Uniqueness is also enforced in the controller with check-then-act: `ExistsForVacancyAsync` followed by `SaveAsync` (`SavedVacanciesController.cs:113-118`). This is not atomic, so two concurrent POSTs can create duplicates. After that, the `FirstOrDefault` fallback returns whichever duplicate it hits first.

   The same field-by-field `SavedVacancyDto` projection is copied twice (`SavedVacancyRepository.cs:40-47` and `65-72`). Copy-paste also appears in `CreateVacancyRequest.cs:12-137` vs `UpdateVacancyRequest.cs:12-127` (the same validation rules, with error texts already drifting apart) and in the mapping code at `VacancyRepository.cs:192-211` vs `224-243`.

   *Suggestion:* drop the fallback lookups. If lookup by vacancy is needed, expose it as an explicit route such as `GET /saved-vacancies/by-vacancy/{vacancyId}`. Make "one bookmark per vacancy" a rule the repository enforces itself, with an atomic `TryAdd` keyed by `VacancyId` that returns a created/duplicate result for the controller to map to 201/409. Extract a single projection helper. Move the shared vacancy fields and their validation into one reusable type that the create and update requests both use.

3. **Comments repeat the code, contracts go undocumented, and no analyzer or linter checks either** — Almost every line of `src/api/Program.cs:13-73` has a comment repeating the statement below it (e.g. `:21`, `:28`, `:71`). `ApiControllerBase.cs:48, 54, 67, 74, 86, 92` repeat the same "create error structure / return HTTP N" comment in each helper. Meanwhile the interfaces, where behaviour actually needs explaining, have no XML docs at all (`src/api/Services/IVacancyRepository.cs:8-15`, `ISavedVacancyRepository.cs:7-14`). Examples: `UpdateAsync` returns `null` for "not found", and `GetByIdAsync` accepts two kinds of id. `<NoWarn>$(NoWarn);1591</NoWarn>` (`Waterfall.Api.csproj:8`) turns off the compiler warning that would flag these gaps.

   The tooling does not enforce anything either. `src/api` has no `.editorconfig`; the only one is `src/waterfall.UI/.editorconfig`. There is no `AnalysisLevel` and no warnings-as-errors. The CI job only restores and builds (`.github/workflows/ci.yml:30-36`), and there are no tests. The stray blank lines and trailing whitespace in `ApiControllerBase.cs:23-39` and `SavedVacancyRepository.cs:100` show that no formatter runs.

   *Suggestion:* keep only comments that explain *why*, and document the repository interfaces instead. Remove the global 1591 suppression, or limit it to generated code. Add a root `.editorconfig` plus a `Directory.Build.props` with `<AnalysisLevel>latest-recommended</AnalysisLevel>`, `<EnforceCodeStyleInBuild>true</EnforceCodeStyleInBuild>` and `<TreatWarningsAsErrors>true</TreatWarningsAsErrors>`. Add `dotnet format src/api/Waterfall.Api.csproj --verify-no-changes` and a test step to CI.

### Potential vulnerability or risk
**Anyone can write to the catalog without logging in, and the data in memory has no size limit (broken access control plus memory-exhaustion DoS)**

**Location:**
- There is no authentication anywhere. `AddAuthentication` and `[Authorize]` appear nowhere in `src/api`. `app.UseAuthorization()` (`src/api/Program.cs:146`) therefore enforces nothing.
- CORS allows any origin, method and header (`Program.cs:81-89, 143`).
- Every write endpoint is anonymous: `VacanciesController.cs:97` (POST), `:130` (PUT), `:162` (DELETE), and `SavedVacanciesController.cs:99` (POST), `:141` (DELETE).
- Data is held in process-wide singleton dictionaries (`VacancyRepository.cs:11`, `SavedVacancyRepository.cs:11`). Saved vacancies are a single global list, not one per user.
- Input size is unbounded. `description` has only a minimum length (`CreateVacancyRequest.cs:34-37`, `UpdateVacancyRequest.cs:34-37`). `skills` has no limit on item count or item length (`CreateVacancyRequest.cs:126-127`, `UpdateVacancyRequest.cs:109-110`).
- There is no rate limiting and no request-size limit.

**Impact:**
- Anyone who can reach the API can delete or overwrite any vacancy. They can also post fake listings whose `source_url` passes `[Url]` but points to a phishing site that the client app will open.
- Anyone can list and delete every user's bookmarks, which is the IDOR the team's own threat model describes (THR-12).
- Repeated POSTs with large bodies (Kestrel allows about 30 MB per request by default) are kept in memory forever, until the process runs out of memory and crashes, losing all stored data.
- Every `?search=` call lower-cases every stored description (`VacancyRepository.cs:139-143`), so a few huge records also make each search very CPU-heavy.

The design doc defers JWT only for saved vacancies (`docs/api/api-design.md:10`). Catalog writes are not covered at all, so these endpoints are unauthenticated by design, not just unfinished. A stub is expected for Lab 4, but this access-by-default should be fixed before the API runs anywhere reachable.

**Mitigation:**
- Make endpoints closed by default: `AddAuthentication().AddJwtBearer(...)` plus a fallback authorization policy of `RequireAuthenticatedUser()`.
- Mark only the catalog `GET` actions `[AllowAnonymous]`, and put the catalog write endpoints behind a role policy (employer / collector service).
- Key saved vacancies by the `user_id` taken from the token, never from the request.
- Add upper bounds: e.g. `[StringLength(10000, MinimumLength = 20)]` on `description`, and a validator capping `skills` at about 30 items of 50 characters or fewer.
- Set Kestrel `Limits.MaxRequestBodySize` to roughly 64 KB and add `AddRateLimiter` on the write routes.
- Replace `AllowAll` CORS with an explicit origin list. The native MAUI client does not need CORS at all.

</details>

## Comparison between human and AI review

Given the correct prompt and the context of requirements on the code review criteria used on the course, Claude has described more points than we did and in much greater detail, listing the exact paths and lines for the errors or lines of interest. Additionally, Claude has explored each problem in much more detail, unveiling more issues than we did.

In general, the responses overlap; we suspect that this is due to the "obviousness" of the strengths and weaknesses (given the small number of actual points to explore given the code from Lab04). However, there are some disagreements: where Claude has named usage of controllers as a good thing for consolidating business logic, we believe that this makes the framework code seep into the business logic, making future change of the API framework and/or reuse of business logic much harder, which in the future will require refactoring. Some misses of Claude were inconsistent commenting between modules (like MCP using English) and the bad practice of using non-English comments in the main code.

No AI was used in the comparison between human and AI review.

## Feedback on our code

The pun-intended team reviewed our Lab 4 code at commit `8dbbe90`
([their report](https://github.com/ukma-fin-ssdm-2026/pun-intended-team/blob/main/docs/code-quality/review-report.md)).
Below is each point and what we did with it.

| Point | Source | Status | What we did |
|---|---|---|---|
| AI usage notes should name who checked the document | In class | Done | The Lab 5 documents name the person who checked them |
| Ruff `D` finds 98 missing docstrings | In class | Rejected | Our standard keeps docstrings to those that state a contract (`AGENTS.md`, "Comments"), so `pyproject.toml` disables the `D` rules on purpose |
| `ruff format --check`: 10 files need reformatting | In class | Done | The count came from Ruff's default line length, 88, while ours is 100. `ruff format` now runs on every commit and in CI |
| Inconsistent boolean names (`use_builtin_model`, `redact_speaker_names`, `link_active`, `accept_terms`) | In class | Accepted, not done | Valid. Only `use_builtin_model` and `redact_speaker_names` are implemented so far; the names get the `is_`/`has_` form when their operations are built |
| Fixture names hide what they return or raise (`transcribed()`, `folder_in()`) | In class, AI | Done | The demo fixtures are gone; the routes read the database through the modules' services |
| Handlers hold business logic (`list_meetings`, `upload_recording`) | In class, AI | Partly done | `list_meetings` now only maps the query to the Meetings service's filter. `upload_recording` still orchestrates storage, persistence and the transcription job in the route |
| The `name` filter is a plain `str`, not `DisplayText` | In class (risk) | Rejected | Not a vulnerability: the filter is 1 to 200 characters, stripped, and only used for a case-insensitive substring match. It is never stored or returned |
| Validation errors echo the rejected input, passwords included | AI (risk) | Done | Only query and path values are echoed now, with regression tests ([static analysis](static-analysis.md), "Validation errors echoed the rejected password") |
| Meeting routes ignore the signed-in user, so there is no authorization | AI | Done | Meeting operations check the signed-in user's access through Access Policy |
| Almost no tests | AI | Done | 484 tests, 279 of them on every commit |
| The upload size is checked only after the body is spooled | AI | Done | Oversized requests are refused before the multipart body is parsed, and streamed bytes are counted when `Content-Length` is missing or understated |
| FFmpeg decodes uploads in the API process | AI | Accepted | The API decodes only the first audio frame, to refuse a file that is not audio before it is stored. The ASR worker does the full decode |
| The MCP endpoint needs no key | AI | Done | The MCP server now requires a personal MCP key and reads only meetings its owner can access |
| Secrets compared with `!=` | AI | Done | Passwords are verified with argon2id, and session tokens are looked up by their hash |
| Sign-out does not end the session | AI | Done | Sign-out deletes the session |

This section was drafted with Claude Code (Claude Opus 5.5), which checked each point against the
code; Andrii Shalaiev reviewed the statuses and decisions.

## AI Usage

The human review and the human-to-AI comparison explicitly state above that no AI was used for
them. Claude Code (Claude Opus 5.5) produced the separate AI review and drafted the follow-up
status table; the named team members reviewed those results. OpenAI Codex added this consolidated
disclosure while preparing the midterm documentation update.
