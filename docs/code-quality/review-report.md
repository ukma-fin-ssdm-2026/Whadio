# Review: Waterfall

Team's repository URL: <https://github.com/ukma-fin-ssdm-2026/waterfall/tree/main>
Reviewed commit SHA: `ee2c003582951b07d7e12e453d7739e03c35b619`.

**State:** preliminary, will be enhanced later.

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