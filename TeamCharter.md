## 1. General Information
- Team Name: sztorm@localhost:3000
- Members:
    - Andrii Shalaiev (GitHub: @Hukyl, NaUKMA email: a.shalaiev@ukma.edu.ua)
    - Zlata Tsepkalo (GitHub: @t-zlata, NaUKMA email: z.tsepkalo@ukma.edu.ua)
    - Valeriia Missirova (GitHub: @v-missirova, NaUKMA email: v.missirova@ukma.edu.ua)
    - Denys Zabiiaka (GitHub: @SquidBow, NaUKMA email: d.zabiiaka@ukma.edu.ua)

## 2. Roles and Responsibilities
- Repository Maintainer, Quality Lead: Zlata
- CI Maintainer, Requirements Lead: Andrii
- Documentation Lead: Valeriia
- Issue Tracker Lead, Traceability Lead: Denys

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
- Code review rules: each PR requires at least one approval. Automated review is done by CodeRabbit.
- Issue workflow: open issue -> assign -> work -> pull request -> AI checks -> fix or address all issues highlighted by the AI code checker -> PR -> close.
- Definition of Done: every issue lists clear acceptance criteria before work starts on it. A task is considered completed when the code meets these criteria, passes all tests and automated checks, receives reviewer approval, and is successfully merged into the `main` branch.
- Task priority labels:
    - `high priority` — critical tasks that block the work of other members, stop CI/CD pipelines, or are mandatory for the nearest deadline. These are taken into work first.
    - `low priority` — minor improvements, refactoring, or non-critical tasks that do not block the team. Executed in the background when free time is available.

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

## 8. AI Usage
- Tools: coding agents, chat models
- Disclosure rules: indication of AI usage in files
- Verification rules: 
    - generated code must undergo review and testing before merging;
    - unverified generated code cannot be merged into the main branch;
    - responsibility for anything generated lies solely with the person who generated it

## 9. Signatures
- [x] Andrii (GitHub: @Hukyl)
- [x] Zlata (GitHub: @t-zlata)
- [x] Valeriia (GitHub: @v-missirova)
- [x] Denys (GitHub: @SquidBow)

## AI Usage
This document was prepared with the assistance of AI (Gemini 3.1 Pro). The author reviewed and edited the content, and the document is reviewed through a pull request before merging.