# Debugging log: off-by-one retry limit

Issue [#82](https://github.com/ukma-fin-ssdm-2026/Whadio/issues/82), Lab 6.

## Symptom

### 1. Reproduce

Changing the retry condition from `<` to `<=` caused a meeting to remain `queued` instead of
becoming `failed` after the fifth unsuccessful attempt (`MAX_ATTEMPTS = 5`). The transcription
test recorded another `TranscriptionRequested` for a job already at that limit. This would
allow a sixth attempt and repeat GPU work after the retry budget was exhausted.

Verification used `main` at
[`4bc60c91`](https://github.com/ukma-fin-ssdm-2026/Whadio/commit/4bc60c91654732d088b0f474226d1a7210203403)
with the three publication regression tests listed under Fix added to it. The same tests were
run before injecting the fault, with the fault, and after restoring the condition. All suite
results below come from the **fast suite**, which excludes tests marked `slow`:

```sh
uv run --frozen pytest -q -m "not slow"
```

| Condition | Result |
|---|---|
| Strict `<` before injection | 460 passed, 321 slow tests deselected |
| Injected `<=` | 2 failed, 458 passed, 321 slow tests deselected |

[`test_retryable_failure_past_the_attempt_limit_fails_the_meeting`](../../src/whadio/processing/test_services.py#L845) reports `QUEUED` instead of `FAILED`.
[`test_job_at_the_attempt_limit_is_not_published_again`](../../src/whadio/processing/test_services.py#L819) reports an unexpected request instead of an empty publication list.

## Cause

### 2. Isolate

The failing tests exercise `ProcessingService` with in-memory repositories and a publisher that
records requests. The notes test checks the meeting's state; the transcription test checks
whether another request is published.
`PROVIDER_UNAVAILABLE` and `AUDIO_LINK_EXPIRED` are retryable failures, so both reach the retry
decision without involving a database, broker or GPU worker.

### 3. Diagnose

[`ProcessingService._failed`](../../src/whadio/processing/services.py#L289)
chooses whether to retry the job or mark it as failed. The injected change was:

```diff
-        if result.reason.retryable and job.attempts < MAX_ATTEMPTS:
+        if result.reason.retryable and job.attempts <= MAX_ATTEMPTS:
```

`job.attempts` includes the attempt that just failed. When it equals five, the `<` condition
rejects another retry. Changing it to `<=` allows a sixth attempt.

## Fix

### 4. Fix and rerun

Restoring `<` made both failing tests pass. A retryable failure below the limit requeues the job;
at the limit, the job and meeting are marked as failed. Rerunning the same fast suite after
restoring the condition gave **460 passed, 321 slow tests deselected**.

### 5. Prevent a repeat

The existing notes test checks that the meeting becomes `failed`. The transcription tests below
check whether another request is published at each boundary point:

| Attempts consumed | Expected publication | Regression test |
|---|---|---|
| `MAX_ATTEMPTS - 1` (4) | Publish the same job again | [`test_retryable_failure_one_attempt_before_the_limit_publishes_the_job_again`](../../src/whadio/processing/test_services.py#L806) |
| `MAX_ATTEMPTS` (5) | Publish nothing | [`test_job_at_the_attempt_limit_is_not_published_again`](../../src/whadio/processing/test_services.py#L819) |
| `MAX_ATTEMPTS + 1` (6) | Publish nothing | [`test_job_above_the_attempt_limit_is_not_published_again`](../../src/whadio/processing/test_services.py#L832) |

The below-limit test also failed when the condition was changed to
`job.attempts < MAX_ATTEMPTS - 1`. That fault stops retries one attempt too early and was not
caught by the earlier tests at 1 and 5.

## Lesson

Next time we introduce or change a limit, we will test just below, on and just above it together,
as agreed at the 2026-10-15 meeting. For this retry limit, that means checking that a failure on
the fourth attempt allows a fifth attempt, while a failure at or above five allows no further
attempt. We will check both the meeting's state and whether another worker request is published.

## AI Usage

Claude Code was used for the original exercise, checked by Denys Zabiiaka.
OpenAI Codex revised this log, added the boundary tests and ran the verification reported here.
Valeriia Missirova is responsible for reviewing the results and for the document.
