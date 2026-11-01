## 1. General Information
- Team Name: sztorm@localhost:3000
- Members:
    - Andrii Shalaiev (GitHub: @Hukyl, NaUKMA email: a.shalaiev@ukma.edu.ua)
    - Zlata Tsepkalo (GitHub: @t-zlata, NaUKMA email: z.tsepkalo@ukma.edu.ua)
    - Valeriia Missirova (GitHub: @v-missirova, NaUKMA email: v.missirova@ukma.edu.ua)
    - Denys Zabiiaka (GitHub: @SquidBow, NaUKMA email: d.zabiiaka@ukma.edu.ua)

## 2. Roles and Responsibilities
- Repository Maintainer, Quality Lead, Data & Threat Modeler, API Documentation Lead, Code Reviewer, Test Strategist, Review Manager, AI Code Reviewer: Zlata
- CI Maintainer, Requirements Lead, Architecture Lead, Backend Lead, Code Quality Lead, Integration Lead, Test Planner: Andrii
- Documentation Lead, Integration Lead, Debugging Lead, AI Code Reviewer: Valeriia
- Issue Tracker Lead, Traceability Lead, Requirements-Architecture Mapper, API Quality Lead, Security Analyst, Test Lead, Quality Analyst: Denys

## 3. Communication Plan
- Primary channel: Telegram chat, Google Meet calls
- Meeting schedule: online meetings on demand, approximately once a week
- Response expectations:
    - no more than 6 hours during working hours;
    - if less than 24 hours to the deadline -> 1 hour
    - *soft deadline*: assigned tasks should preferably be completed 24 hours before the deadline

## 4. Collaboration and Workflow
- Branching strategy: branches for issues (resolves / relates to) + pull requests to main.
- Branch naming: `type/#<issue-number>-short-description` format is used (e.g., `docs/#3-teamcharter-setup`).
- Commit practices:
    - intermediate results that pass tests and do not break the core system;
    - final results.
- Commit conventions: `<type>(#<issue-number>): short message` format is used (e.g., `docs(#3): add TeamCharter.md`).
- Dependency updates: Dependabot's pull requests are not tied to issues; their branches keep the `dependabot/...` names, and their commits use `build(deps): ...` or `build(deps-dev): ...`.
- Issue workflow: open issue -> assign -> work -> pull request -> AI-assisted review -> address every review comment -> merge -> close.
- Code review rules and Definition of Done: see section 11.
- Task priority labels:
    - `high priority` — critical tasks that block the work of other members, stop CI/CD pipelines, or are mandatory for the nearest deadline. These are taken into work first.
    - `low priority` — minor improvements, refactoring, or non-critical tasks that do not block the team. Executed in the background when free time is available.
    - `documentation` — improvements or additions to documentation.
    - `enhancement` — new feature or request.
    - `feedback` — instructor's feedback; not included in the tracker grading.
    - `bug` — something isn't working.
    - `disregarded` — this will not be worked on.
    - `duplicate` — this issue or pull request already exists.
    - `help wanted` — extra attention to the problem is needed.
    - `invalid` — this doesn't seem right.
    - `question` — further information is requested.
- Requirements Collaboration Practices:
    - Joint analysis of requirements and tasks during team meetings.
    - User stories are subject to peer review before being merged into the `main` branch.
    - Non-functional requirements (NFRs) are verified through joint review sessions and checked against defined measurable criteria.
- Artifact Management:
    - All requirement documents must be stored in the `/docs/requirements/` directory of the repository.
    - The team is responsible for maintaining the `README.md` with up-to-date links to all relevant documentation.

## 5. Conflict Resolution
- Conflict resolution plan:
    - joint discussion -> majority vote,
    - upon failure -> appeal to the instructor

## 6. Availability and Workload
- Member availability:
    - Andrii: 6 hours/week, can be disturbed anytime
    - Zlata: 5-6 hours/week, disturb only during working hours
    - Valeriia: 6 hours/week, can be disturbed anytime
    - Denys: 5 hours/week, disturb only during working hours

Working hours = 08:00-22:00
Overload -> notify in the primary channel -> brief discussion and selection of an available person to help

## 7. Ethical and Professional Conduct
- Core principles:
    - adhere to academic integrity rules and the ACM Code of Ethics;
    - zero plagiarism: all borrowed materials must have proper attribution to the author;
    - mutual respect

## 8. Individual Responsibility
- Loom Presentations: Each member must record a Loom video demonstrating their specific contributions to the project, such as formulated user stories, non-functional requirements (NFRs), etc.
- Mutual Acknowledgment: During their individual Loom presentations, every member must mention the other team members and briefly acknowledge their respective contributions to the project.
- Evidence Collection and verification: All project changes and individual contributions are openly discussed and validated during regular team meetings. Additionally, the team will review each other's drafts prior to final recording to ensure the accuracy of the claimed contributions and mutual acknowledgments.

## 9. AI Usage
- Tools: coding agents, chat models
- Disclosure rules: indication of AI usage in files and in PR review summaries
- Verification rules:
    - generated code must undergo review and testing before merging;
    - unverified generated code cannot be merged into the main branch;
    - responsibility for anything generated lies solely with the person who generated it

## 10. Signatures
- [x] Andrii (GitHub: @Hukyl)
- [x] Zlata (GitHub: @t-zlata)
- [x] Valeriia (GitHub: @v-missirova)
- [x] Denys (GitHub: @SquidBow)

## 11. Code Quality and Review Policy
- Coding standard:
    - Python: PEP 8, enforced by `ruff format` and by `ruff check` with every rule enabled; strict types, checked by ty and basedpyright; the house rules in `AGENTS.md`, "Code standards";
    - frontend and extension: formatted by Biome and checked by its recommended lint rules, the React and accessibility rules included; every rule exception sits in `frontend/biome.jsonc` with a reason, and `extension/biome.jsonc` extends it.
- Mandatory tools: Ruff, Biome, ty, basedpyright, Bandit, import-linter, deptry, gitleaks, zizmor, actionlint, typos, pytest, uv audit, npm audit and Dependabot; `docs/code-quality/static-analysis.md` lists what each one checks.
- Where the checks run:
    - every commit: the pre-commit hooks, the fast tests included, and Biome when the commit touches the frontend or the extension;
    - every push: the whole test suite, which fails below 85% line and branch coverage, so the push needs the Compose services and `WHADIO_TEST_DATABASE_URL`;
    - CI, on every push and pull request: the same hooks on all files, Biome included, the whole test suite against the Compose services with the same coverage gate, the dependency audit (uv audit, and npm audit for the frontend, its build tools included), a secret scan of the whole history, and the pull request title and commit messages;
    - checks are never bypassed (`--no-verify`, `SKIP=`), and inline suppressions are refused: a false positive gets a scoped exception in `pyproject.toml` or `frontend/biome.jsonc` with a one-line reason, in its own pull request.
- Code review rules:
    - each PR requires at least one approval, and the reviewer submits the review themselves;
    - AI-assisted review: the reviewer goes through the PR with an AI agent, discusses its findings, and posts only the comments they agree with and can justify. The agent, the depth of discussion, and how comments reach GitHub (inline, in the summary, drafted by the agent as a pending review) are the reviewer's choice. PRs that only add report links or signatures are exempt;
    - the reviewer answers for every posted comment as their own, and the review summary names the AI tool used and states that the reviewer verified each point.
- Definition of Done: every issue lists clear acceptance criteria before work starts on it. A task is considered completed when the code meets these criteria, passes all tests and automated checks, receives reviewer approval, and is successfully merged into the `main` branch. In particular:
    - formatting: every commit-hook check passes, locally and in CI;
    - tests: new behaviour has tests next to the code it tests, in the Arrange-Act-Assert form, covering edge cases and refusals;
    - documentation: the documents governing the change are updated, the OpenAPI specification is regenerated with any route or schema change, and AI use is disclosed.
- Responsible roles:
    - Code Quality Lead (Andrii): maintains the tools, the hooks and CI, and reports the static analysis results;
    - Code Reviewer (Zlata): reviews other teams' code;
    - Security Analyst (Denys): checks how the code handles data, and triages security findings;
    - Documentation Lead (Valeriia): keeps the charter and the reports up to date;
    - every member reviews teammates' pull requests, and each module owner answers for the quality of their module.

## AI Usage
This document was prepared with the assistance of AI (Gemini 3.1 Pro); the review rules were revised, and section 11 and the Lab 5 roles were drafted, with Claude Code (Claude Opus 5.5). The author reviewed and edited the content, and the document is reviewed through a pull request before merging.
