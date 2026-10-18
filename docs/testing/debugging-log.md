# Debugging log: off-by-one retry limit

### The bug

In `src/whadio/processing/services.py`, `ProcessingService._failed` decides whether a failed job is retried or the meeting fails. We broke its boundary on purpose:

```diff
-        if result.reason.retryable and job.attempts < MAX_ATTEMPTS:
+        if result.reason.retryable and job.attempts <= MAX_ATTEMPTS:
```

With `MAX_ATTEMPTS = 5`, a job that has already run five times is queued for a sixth run instead of failing the meeting.

### 1. Reproduce

The full suite went from 570 passed to 1 failed, 569 passed:

```text
FAILED src/whadio/processing/test_services.py::test_retryable_failure_past_the_attempt_limit_fails_the_meeting
E   state: <ProcessingState.QUEUED: 'queued'> != <ProcessingState.FAILED: 'failed'>
```

### 2. Isolate

Rerunning only that test with `-vv` fails the same way in 0.08 s, so the cause lies in Processing's own logic, not in the database or ordering between tests (the test uses in-memory fakes). The test sets up a job with `attempts=MAX_ATTEMPTS` and sends a retryable `NotesFailed`. The meeting ends up `queued`, which only the retry branch of `_failed` produces.

### 3. Diagnose

`_failed` is the only place that chooses between `requeue` and `finish`. Its condition compares `job.attempts` to `MAX_ATTEMPTS`. With `<=`, the job at the limit (`attempts == 5`) still counts as having attempts left. This is an off-by-one error on the boundary.

### 4. Fix and rerun

We restored `<`. The full suite passes again: 571 passed, including the new test below.

### 5. Prevent a repeat

The existing test checks the meeting's state. The user-visible damage of this bug is different: the worker gets the job a sixth time. We added a regression test for exactly that, in [`processing/test_services.py`](../../src/whadio/processing/test_services.py):

```python
def test_job_at_the_attempt_limit_is_not_published_again() -> None:
    # Arrange
    pipeline = make_pipeline()
    job_id = add_job(pipeline, JobType.TRANSCRIPTION, attempts=MAX_ATTEMPTS)
    handle(
        pipeline, transcription_failed(pipeline, job_id, TranscriptionFailure.AUDIO_LINK_EXPIRED)
    )
    # Act
    requests = publish_all(pipeline)
    # Assert
    assert requests == []
```

With the bug in place it fails, because one extra `TranscriptionRequested` is published. With the fix it passes.

## Lesson

At a retry boundary, distinguish attempts already consumed from attempts still available.
The existing state test detected the wrong terminal state; the additional regression checks
the downstream consequence: no sixth request is published. Use in-memory collaborators to
isolate the decision before investigating infrastructure, and check both state and side effects.

## Current verification (2026-10-18)

The same `<` to `<=` fault was reproduced in a disposable Linux copy with Python 3.13.16.

| Phase | Observed result |
|---|---|
| Existing state test and new publisher regression before injection | 2 passed |
| Existing state test with the fault | 1 failed: queued instead of failed |
| Publisher regression with the fault | 1 failed: an extra TranscriptionRequested |
| Both tests after restoring `<` | 2 passed |
| Current complete fast suite after repair | 313 passed, 296 slow tests deselected |


The temporary production source was restored in a `finally` block and verified byte-for-byte.
Main already contains the correct `<` condition; this branch adds the publisher regression and
this record, without changing production code. This debugging exercise is separate from the
individual new-feature TDD assignment.

## AI Usage

The supplied lab record credits Claude Code (Claude Opus 5.5), checked by Denys Zabiiaka.
OpenAI Codex later adapted the record, added the publisher regression to the current branch and
performed the fresh isolated reproduction. Reviewed by Missirova Valeriia and PR.
