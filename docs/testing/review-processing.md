# Review processing

Relates #400. Authors enable native auto-merge themselves; this automation never enables it or
merges a PR. The required `Review processed` commit status waits for an approval of the current
head by a collaborator with write, maintain or admin permission. Existing approval and CI rules
continue to apply.

A clean approval releases the gate. An approving review containing `Nit:` at the beginning of a
line (case insensitive), in its summary or inline comments, switches the PR to manual merging.
The processor disables auto-merge and confirms cancellation before passing the status. Nits stay
optional: the author may merge manually after processing. Another approval cannot override this
manual decision, which lasts for the lifetime of the PR and is saved in a bot-authored conversation
comment. Do not edit or delete that comment.

Telegram receives one grouped notification per approving review with nits, linking to the PR and
review. Delivery happens after releasing the gate; failures are reported and retried without
blocking manual merges. Saved review IDs prevent ordinary duplicate delivery. A crash between
delivery and saving its ID can still produce a duplicate. Missing secrets are reported without
printing credentials or HTTP error URLs.

Manual merges also wait for processing after approval. Two short hosted jobs normally process
a review; runner queues and failures can extend the wait. Reconciliation runs every five minutes
and supports manual dispatch. Jobs time out after five minutes. New commits need fresh approval,
even though the existing native review rule retains old approvals.

## Trust and timing

`review-signal.yml` receives review events with no permissions, checkout or artifacts. Its
completion wakes the privileged processor, which checks out only `refs/heads/main`, ignores event
payloads and artifacts, and fetches current GitHub state. Lifecycle events, schedule and manual
dispatch also reconcile every open PR. Repository-wide concurrency serializes processing, so a
coalesced queued run does not lose a review.

The processor uses `GITHUB_TOKEN` with pull-request and status write permissions. It never writes
commits or directly merges. Verify cancellation permissions and native auto-merge's downstream
release triggers in a controlled PR before rollout. A direct merge using this token can suppress
downstream workflows; there is deliberately no direct-merge fallback.

The required status must be installed before relying on this protection. Missing status blocks
the first approval until inspection; a new head SHA needs its own status. Submit the verdict and
inline nits together. Later comments, additional reviews, or re-enabling auto-merge after a
successful status can race with merging; cancellation cannot prevent an already-permitted merge.
PRs sharing a head SHA also share statuses: avoid multiple PRs to `main` from the same commit while
relying on this gate.

## Rollout

1. Merge after review with `REVIEW_PROCESSING_ENABLED` unset. This is read-only dry-run mode,
   including Telegram; inspect Actions logs for proposed decisions.
2. Configure repository Actions secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. The existing
   reminder's November 17, 2026 run had an empty chat ID and HTTP 400; verify the current values.
3. Set repository Actions variable `REVIEW_PROCESSING_ENABLED` to exactly `true` and dispatch the
   processor. Confirm the `Review processed` status on a controlled PR.
4. Create a **separate** active `main` branch ruleset requiring `Review processed` from GitHub
   Actions. Add only the existing `whadio-release-bot` app as a PR bypass actor for this ruleset.
   Do not add a bypass to `main-checks` or weaken its four existing CI checks.
   The processor emits no status for PRs authored by `whadio-release-bot[bot]` from the protected
   `chore/#275-release` branch in the same repository: release PRs have no human approval, and
   the existing release job waits for all reported checks, including optional ones.
5. With the gate required, test author opt-in before approval, clean approval, approval with
   inline nits, manual merging with nits, and a fresh push requiring another approval. Verify
   cancellation precedes releasing the gate and the release workflow starts after a clean merge.
6. Verify cancellation failure keeps the gate blocked, notification failure leaves it released,
   and retries do not ordinarily duplicate notifications. Record dry-run and controlled-PR
   evidence in the implementation PR before considering rollout complete.

To roll back, first disable only the new review-processing ruleset, then unset the variable.
Unsetting it while retaining the required status can block new PRs. Authors remain responsible
for any existing native auto-merge requests during rollback.

## Local verification

Run `uv run pytest .github/scripts/test_review_processing.py`, the standalone-script tests, Ruff,
ty, actionlint and zizmor on the changed files. Tests use fake GitHub and Telegram responses and
do not send messages or change repository settings.

## AI Usage

Written with Codex.
