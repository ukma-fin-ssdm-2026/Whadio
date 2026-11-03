---
name: pr-review
description: Review a Whadio pull request together with the reviewer in four stages - report the pull request's state, review it against its issue, AGENTS.md and the governing documents, present the findings as Blocking, Question and Nit, then post the points the reviewer chooses as one GitHub review with inline comments. Use it when asked to review a pull request, to check a teammate's changes, or to post review comments.
---

# PR review

You review a pull request with the reviewer: the teammate who submits the review and answers for
every comment in it (`TeamCharter.md`, section 11). You collect and check; the reviewer decides
what is said. Stop where a stage says so.

## Rules

- Work on the pull request's head in a worktree of its own, read-only. Never push, commit to the
  author's branch, edit the pull request, or resolve threads.
- Every finding carries its evidence: a `file:line`, the document line it breaks, a command and its
  output, a failing test or a screenshot. Drop what you cannot back.
- Review what the pull request changes. A problem that was already on the base branch is not a
  finding; offer it to the reviewer as a separate issue.
- Skip what the checks enforce (formatting, lint rules, import contracts, types) unless CI is red on
  it. Point to an existing pattern in the repository rather than to your preference.
- "No findings" is a valid result.
- Post nothing before stage 4, and in stage 4 only what the reviewer chose.

## Stage 1: report the state, then stop

Collect, with `<n>` the pull request's number:

```bash
gh pr view <n> --json number,title,author,isDraft,baseRefName,headRefName,headRefOid,mergeStateStatus,reviewDecision,closingIssuesReferences,additions,deletions,changedFiles,body
gh pr checks <n>
gh pr diff <n> --name-only
gh issue view <issue>
```

- **Issue:** the linked issue's acceptance criteria and which are ticked. A pull request without
  `Closes #` or `Relates #` is a finding in itself.
- **Base:** is it `main`, or another pull request's branch (stacked)? Is it behind its base?
- **CI:** each red or pending check; for a red one, the failing step from
  `gh run view <run-id> --log-failed`.
- **Size:** additions and deletions without lockfiles and generated files (`*.gen.ts`,
  `docs/api/openapi-generated.*`).
- **Context:** the governing documents the changed paths fall under (the table in `AGENTS.md`, "The
  project"), recent commits on the pull request's base (`baseRefName`: `main`, or the parent pull
  request's branch when stacked) that touch the same files
  (`git log --oneline -5 origin/<base> -- <paths>`), and other open pull requests on them.
- **Earlier reviews:** open threads and whether the author answered them
  (`gh api repos/{owner}/{repo}/pulls/<n>/comments`).

Report this in about 15 lines, then wait. The reviewer may narrow the review or stop it here.

## Stage 2: review

1. Check out the head: `git fetch origin pull/<n>/head`, then
   `git worktree add --detach ../whadio-review-<n> <headRefOid>`. Install what the checks you run
   need there (`AGENTS.md`, "Setup"). Remove it after posting, as `references/posting.md`,
   "Sending it", describes.
2. Read the diff against the merge base (`git diff origin/<base>...<headRefOid>`), the whole of each
   changed file where the hunk is not enough, and the callers of changed functions.
3. Check, in this order:
   - **The issue.** Each acceptance criterion: met, partly met or missing, with the file or test that
     shows it. Work the issue did not ask for.
   - **The governing documents.** Does the change agree with them, and does it update them where
     its behaviour changes: `docs/api/api-design.md` Status, `docs/requirements/rtm.md` (its rows
     cite `TC-` cases from `docs/validation/test-plan.md`), `docs/architecture/`? When the code
     and a document disagree, that is a finding.
   - **Architecture.** `AGENTS.md`, "Layout", "Inside a module" and "Dependency rules": the right
     module and file, routes that only translate HTTP, collaborators passed through constructors.
   - **Code standards.** `AGENTS.md`, "Code standards": strict types without escape hatches,
     validated boundaries, `Field(description=...)`, settings in `.env.example`, comments only
     where they earn their place, and the threat model's rules on secrets, tokens and meeting
     content.
   - **Tests.** `AGENTS.md`, "Tests use pytest", and `docs/testing/testing.md`, section 4 for the
     SPA: placed next to the code, names that state the behaviour, `Arrange`/`Act`/`Assert`, one
     logical assertion each, edge cases and refusals, `@pytest.mark.slow` where it applies.
   - **Test strength.** Break each new guard, branch or fix and run the tests that should notice:
     - if the change touches the scope of `[tool.mutmut]` in `pyproject.toml`, run
       `uv run task mutation` and read the survivors;
     - elsewhere, by hand in the review worktree: flip a condition, drop a call or change a constant,
       run the narrowest test (`uv run pytest <file>::<test> -q`,
       `npm --prefix frontend test -- <file>`), then restore the file with
       `git checkout -- <file>`.
     A mutation that leaves every test green is a finding: name the mutation and the test that
     should have caught it.
   - **Generated files and disclosure.** The OpenAPI files, `schema.gen.ts` and `routeTree.gen.ts`
     regenerated with route, schema or route-file changes, and AI use disclosed in the documents the
     pull request writes (`TeamCharter.md`, section 9).
   - **The running app.** If the change alters what the SPA shows, use the `ui-evidence` skill:
     capture the changed screens on the base and on the head, look at them, and treat console errors
     as findings.
4. Check every finding before you keep it. Reproduce it, or show the line, and check whether a
   later commit in the pull request already changes it. Claude Code may hand separate checks to
   subagents; their findings go through the same check.

## Stage 3: present the findings, then stop

Group them for the reviewer, not for GitHub:

- **Blocking:** must change before merging: wrong behaviour, an unmet acceptance criterion, a broken
  rule from `AGENTS.md` or a governing document, or a test gap that lets a bug through.
- **Question:** something the code alone cannot settle. The author's answer may make it Blocking or
  nothing.
- **Nit:** an optional improvement; merging without it is fine.

A severity may follow: **P1** harms users, data or security; **P2** wrong behaviour or a missing
criterion; **P3** maintainability or a weak test; **P4** polish. Blocking is P1 or P2; a Nit is P4.

```text
1. [Blocking · P2] frontend/src/features/workspaces/components/CreateWorkspaceDialog.tsx:37
   Claim: one sentence.
   Evidence: what you ran or read, and what it showed.
   Comment: the text you would post (references/posting.md, "Inline comments").
```

End with the proposed verdict: **Request changes** if anything is Blocking, otherwise **Approve**,
or **Comment** when only questions remain or the reviewer wants to discuss first. Then wait while the
reviewer picks, edits or drops points and settles the verdict.

## Stage 4: post

Post the chosen points as one review, following `references/posting.md`, and give the reviewer its
address.

## AI Usage

This skill was written with Claude Code.
