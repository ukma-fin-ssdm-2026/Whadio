## 1. General Information
- Team Name: sztorm@localhost:3000
- Members:
    - Andrii Shalaiev (GitHub: @Hukyl, NaUKMA email: a.shalaiev@ukma.edu.ua)
    - Zlata Tsepkalo (GitHub: @t-zlata, NaUKMA email: z.tsepkalo@ukma.edu.ua)
    - Valeriia Missirova (GitHub: @v-missirova, NaUKMA email: v.missirova@ukma.edu.ua)
    - Denys Zabiiaka (GitHub: @SquidBow, NaUKMA email: d.zabiiaka@ukma.edu.ua)

## 2. Roles and Responsibilities
- Repository Maintainer, Quality Lead, Data & Threat Modeler: Zlata
- CI Maintainer, Requirements Lead, Architecture Lead: Andrii
- Documentation Lead: Valeriia
- Issue Tracker Lead, Traceability Lead, Requirements-Architecture Mapper: Denys

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
- Disclosure rules: indication of AI usage in files
- Verification rules: 
    - generated code must undergo review and testing before merging;
    - unverified generated code cannot be merged into the main branch;
    - responsibility for anything generated lies solely with the person who generated it

## 10. Signatures
- [x] Andrii (GitHub: @Hukyl)
- [x] Zlata (GitHub: @t-zlata)
- [x] Valeriia (GitHub: @v-missirova)
- [x] Denys (GitHub: @SquidBow)

## AI Usage
This document was prepared with the assistance of AI (Gemini 3.1 Pro). The author reviewed and edited the content, and the document is reviewed through a pull request before merging.