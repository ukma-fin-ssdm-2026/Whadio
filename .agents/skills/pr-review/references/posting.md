# Posting a review

One review per round: the verdict, a short summary and the inline comments, sent in one call.
`gh pr review` cannot attach comments to lines, so the review goes through the REST API.

## The summary

```text
<One or two sentences: what the pull request gets right, and what you ran on which commit.>

Before merging (inline comments):

1. <Blocking point, one line>
2. <Blocking point, one line>

Comments marked "Nit" are optional.

Reviewed with <AI tool>; each point was checked against the code and the tests.
```

- Leave out the numbered list when nothing is Blocking, and the Nit line when there are no nits.
  List open questions after the Blocking points as "Questions (inline comments):" if the verdict
  depends on them.
- Keep the last sentence. Section 11 of `TeamCharter.md` requires the summary to name the AI tool
  and to state that the reviewer verified each point.

## Inline comments

- One point per comment, on the line it is about.
- Start a nit with `Nit: `. Ask a question as a question: "Could you…?", "Is … intended?".
- Say what is wrong, why (the rule or document line, the mutation that stayed green, the
  reproduction) and what would fix it. Point to an existing example in the repository when there
  is one: "as `SignInForm.tsx` does".
- Use a `suggestion` block only when it is the whole fix.
- Plain and short. No praise padding, no restating the diff.

## The payload

Write `review.json` in the review worktree, so it never lands in the repository:

```json
{
  "commit_id": "<headRefOid from stage 1>",
  "event": "REQUEST_CHANGES",
  "body": "<the summary>",
  "comments": [
    {
      "path": "frontend/src/features/workspaces/components/CreateWorkspaceDialog.tsx",
      "line": 37,
      "side": "RIGHT",
      "body": "This handles errors differently from `showServerError` in `SignInForm.tsx`…"
    },
    {
      "path": "frontend/src/features/workspaces/components/CreateWorkspaceDialog.test.tsx",
      "start_line": 41,
      "start_side": "RIGHT",
      "line": 48,
      "side": "RIGHT",
      "body": "Nit: this test checks two behaviours…"
    }
  ]
}
```

- `event` is `APPROVE`, `REQUEST_CHANGES` or `COMMENT`. GitHub refuses the first two on your own
  pull request; use `COMMENT` there.
- `commit_id` is the head you reviewed. If the author pushed since, check the points against the
  new head first.
- `line` counts lines in the file, not in the diff. `side` is `RIGHT` for the new version (added or
  unchanged lines) and `LEFT` for a deleted line. A range adds `start_line` and `start_side`, and
  must stay in one hunk.
- Only lines inside the diff's hunks take comments. Any other line gets `422` ("Line could not be
  resolved"); move that point into the summary with its `file:line`.

## Sending it

Run from inside the repository, where gh fills in `{owner}/{repo}`:

```bash
gh api --method POST repos/{owner}/{repo}/pulls/<n>/reviews --input review.json
```

A `422` rejects the whole review and posts nothing; fix the comment it names and send it again.
The response's `html_url` is the review's address. Check it with
`gh pr view <n> --json reviews --jq '.reviews[-1].state'`, then remove the review worktree.
