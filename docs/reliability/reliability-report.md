# Reliability Report

The findings come from [`scavenger-hunt.md`](scavenger-hunt.md), which also holds each one's
fault → error → failure chain and, in Stage 3, the choice between failing fast and failing safe.
Each fix below names who made it.

## Findings

| # | Finding | Category | Severity | Status |
|---|---|---|---|---|
| F1 | Job publish to RabbitMQ waits without a limit while holding a row lock | B, E | High | Open |
| F2 | Extension requests to the server have no deadline | B, E | High | **Fixed**; not yet checked with a real recording |
| F3 | A failed upload is given up without a log or a word to the user | D, A | Medium | Open |
| F4 | A recording that could not be saved vanishes in an unawaited listener | A, D | High | Open |
| F5 | Object storage calls can block a request for over half an hour | B, E | Medium | Open |
| F6 | The SPA's API client has no deadline | B | Low | **Fixed** |
| F7 | Signing out ignores whether the server ended the session | D | Low | Open |
| F8 | Asking which chunks the server holds fails silently | D | Low | Open |
| F9 | A published job whose message or result is lost is never finished | B, D | Medium | **Fixed** |

## Fixes

### F2. Extension requests to the server have no deadline

Fixed by Zlata Tsepkalo in `fix(#287): give the extension's requests a deadline`,
`fix(#287): keep the extension's deadline under Chrome's fetch limit` and
`fix(#287): report a stalled extension answer as a timeout`.

**Before.** `extension/api.js`: `fetch` waits for as long as the connection stays open, and
`Upload.send()` retries only what throws:

```js
export async function api(method, path, body) {
  ...
  const response = await fetch(`${server}/api/v1${path}`, init);
  ...
  return response.status === 204 ? null : response.json();
}
```

**After.** `extension/api.js:7-36`, `:46-65`: every request, the response body included, runs under
a 25 s deadline, and one that runs out is thrown as a `TimeoutError`, even when Chromium reports the
cut-off body read as an `AbortError`. Signing in (`:88`) gets the same deadline:

```js
export const TIMEOUT_MS = 25_000;

async function withDeadline(request) {
  const abort = new AbortController();
  const timer = setTimeout(
    () => abort.abort(new DOMException("The server did not answer in time.", "TimeoutError")),
    TIMEOUT_MS,
  );
  try {
    return await request(abort.signal);
  } catch (cause) {
    throw abort.signal.aborted ? abort.signal.reason : cause;
  } finally {
    clearTimeout(timer);
  }
}

export async function api(method, path, body) {
  ...
  return withDeadline(async (signal) => {
    const response = await fetch(`${server}/api/v1${path}`, { ...init, signal });
    ...
  });
}
```

**Why 25 s, `/complete` included.** Chrome stops an extension's service worker once a `fetch()`
response has taken 30 s to arrive
([service worker lifecycle](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle)).
The recording's slices live in that worker, so a deadline must fire first, or the fallback goes
with the worker. A first version gave `/complete` 5 minutes, because the server assembles the
recording before it answers; review found that the worker stopped about 30 s in, so that deadline
could never fire. Now `/complete` gets the same 25 s, and a longer assembly leaves the meeting on
the server and a local copy on disk.

**Patterns.** A timeout on each external call, placed innermost (§3.5) so that the retry and the
fallback the upload already had can act on it: a request that runs out is retried with exponential
backoff (1, 2, 4, 8 s) after asking the server which chunks it holds, and once five attempts are
spent the recording is saved as a local file. The deadline uses a plain timer, not
`AbortSignal.timeout`, so the tests' fake clock can move it.

**Failure and recovery.**

| | |
|---|---|
| Response | Fail-safe: losing the call is worse than a slow or duplicated save |
| What the user sees | Nothing while retries succeed. If the server stays silent, the call is downloaded as `whadio-<time>.webm` at hang-up, as for any failed upload. A stalled sign-in shows "The server did not answer in time." in the popup and stores no session |
| Recovery | Automatic: the timed-out chunk is retried, and a chunk the server stored before the answer was lost is skipped. After five failed attempts the local file is the recovery; the user uploads it through the web app by hand |

### F6. The SPA's API client has no deadline

Fixed by Zlata Tsepkalo in `fix(#287): give the web app's reads a deadline` and
`fix(#287): report a read that stalls mid-body as a timeout`.

**Before.** `frontend/src/shared/api/client.ts`: every request waits without a limit, so a query
on a stalled connection never leaves its loading state:

```ts
fetch: (request) => globalThis.fetch(request),
```

**After.** `frontend/src/shared/api/client.ts:17-59`: a `GET`, its body included, gives up after
30 s. The body is read inside the deadline because Chromium rejects a body read cut off by the
signal with an `AbortError` that drops the signal's reason, and the timeout would otherwise look
like a cancellation. The caller's own signal is kept, so React Query can still cancel at once.
`frontend/src/shared/api/unwrap.ts:12-15` turns the timeout into a message that says what happened:

```ts
export const READ_TIMEOUT_MS = 30_000;

async function readWithDeadline(request: Request): Promise<Response> {
  const deadline = new AbortController();
  const timer = setTimeout(
    () => deadline.abort(new DOMException("The server did not answer in time.", "TimeoutError")),
    READ_TIMEOUT_MS,
  );
  try {
    const response = await globalThis.fetch(request, {
      signal: AbortSignal.any([request.signal, deadline.signal]),
    });
    const body = await response.arrayBuffer();
    return new Response(body.byteLength === 0 ? null : body, { ... });
  } catch (cause) {
    throw deadline.signal.aborted ? deadline.signal.reason : cause;
  } finally {
    clearTimeout(timer);
  }
}

...
fetch: (request) =>
  request.method === "GET" ? readWithDeadline(request) : globalThis.fetch(request),
```

```ts
message:
  cause instanceof DOMException && cause.name === "TimeoutError"
    ? "The server did not answer in time. Try again."
    : "Could not reach the server. Check your connection and try again.",
```

**Patterns.** A timeout on reads, then the retry React Query already makes (two more attempts for
anything but a 4xx), then a clear error. Writes are left without a client deadline on purpose: a
recording upload can take minutes, and giving up on a write does not undo it on the server, so a
user who retries could create a meeting twice.

**Failure and recovery.**

| | |
|---|---|
| Response | Fail-fast for reads: an error is better than a page that loads forever, and a read is safe to repeat |
| What the user sees | After the retries run out, the page shows "The server did not answer in time. Try again." where its data would be |
| Recovery | Automatic retries first; after that, the user reloads or revisits the page once the server answers again |

### F9. A published job whose message or result is lost is never finished

Fixed by Andrii Shalaiev in `fix(#294): return published jobs that no worker started to the
queue`, `fix(#294): return running jobs past their limit to the queue`, `fix(#294): fail a job that
has used its attempts instead of publishing it` and `fix(#294): restart the clock of a redelivered
job`.

**Before.** `src/whadio/processing/services.py`: the publisher takes only jobs that were never
published, and nothing looks at a job after its publish:

```python
async def publish_next(self, publisher: IJobPublisher, now: datetime) -> bool:
    job = await self._jobs.next_unpublished()  # queued, published_at is null
    if job is None:
        return False
    ...
    await publisher.publish(request)
    await self._jobs.mark_published(job.job_id, now, context)
    return True
```

**After.** `src/whadio/processing/recovery.py:32-42`, run on each scheduler tick
(`src/whadio/scheduler/services.py:101-107`): a `queued` job published more than 2 days ago goes
back to the publisher with one more attempt, and a `running` job started more than 5 h
(transcription) or 1 h (notes) ago goes back with its attempts as they are. Each limit is a
`WHADIO_JOB_RECOVERY__` setting, and a running limit must exceed its worker's startup and job
timeouts:

```python
async def recover(self, now: datetime) -> int:
    limits = self._limits
    unstarted = await self._jobs.return_unstarted(now - limits.unstarted_limit, BATCH_SIZE)
    running = await self._jobs.return_running(
        {
            JobType.TRANSCRIPTION: now - limits.transcription_running_limit,
            JobType.NOTES: now - limits.notes_running_limit,
        },
        BATCH_SIZE,
    )
    return unstarted + running
```

`src/whadio/processing/repositories.py:181-195` returns at most 50 jobs of each kind, oldest first,
in one statement, and skips a row whose result is being applied (`FOR UPDATE SKIP LOCKED`). The
scheduler only writes the database; the publisher in `web` sends the jobs again.
`src/whadio/processing/services.py:200-203`: a job that comes back with its five attempts used is
failed instead of published:

```python
if job.attempts >= MAX_ATTEMPTS:
    await self._finally_failed(job, now, STALLED, ProcessingFailure.PROCESSING_TIMEOUT)
    return True
```

`:226-227` and `:436`: a start reported again for a running job, as after a redelivery, moves
`started_at` forward, so a job that a second worker runs is not handed back early.

Checked by hand against the Compose RabbitMQ and PostgreSQL, with no worker running, a scheduler
with a 1-minute unstarted limit and a 10-second interval, and `transcription.requests` purged after
each publish. An uploaded recording's job was published at 0 s and again at 90 s, 180 s, 270 s and
360 s, one more attempt each time. At 450 s it failed as `stalled`, the meeting showed
`processing_timeout`, and the failure email reached Mailpit 3 s later.

**Patterns.** A timeout on each job, kept by the scheduler because a lost message raises nothing
anywhere, then a bounded retry: the job is published again, up to the five attempts the queues'
delivery limit also allows. There is no circuit breaker: the scheduler calls nothing but the
database, and a job published again waits in its queue instead of loading a worker. Past the cap,
graceful degradation: the meeting fails with a cause and a notice instead of waiting for ever.

**Failure and recovery.**

| | |
|---|---|
| Response | Fail-safe while attempts remain: a lost job is published again. Fail-fast at the cap: the meeting fails |
| What the user sees | Nothing while a republished job succeeds, only a longer wait. At the cap the meeting shows "Processing took too long and was stopped." and the uploader gets the failure email |
| Recovery | Automatic within the attempts. After that, the member uploads the recording again |

## Reliability tests

The fixes are in JavaScript, so their tests sit next to the code they test, as the repository's
Vitest convention asks, and not under `src/whadio/`. The extension's Vitest configuration collects
only `extension/*.test.js`. Each test injects the failure through a test double that replaces
`fetch` and answers late or never.

| Test | Type | File |
|---|---|---|
| ends a read that gets no answer with a network error saying it timed out | Error handling | `frontend/src/shared/api/client.test.ts` |
| ends a read whose answer stops partway with the timeout message | Error handling | `frontend/src/shared/api/client.test.ts` |
| signing in gives up once no answer has arrived by the deadline | Error handling | `extension/api.test.js` |
| signing in stores no session when it gives up | Error handling | `extension/api.test.js` |
| gives up on a chunk that gets no answer within its deadline and sends it again | External failure (fault injection) | `extension/background.test.js` |
| still saves the call locally when no chunk upload ever gets an answer | External failure (fault injection) | `extension/background.test.js` |
| signing in, and a request, give up on an answer that stops partway as a timeout | External failure (fault injection) | `extension/api.test.js` |
| a read answered after 29999 / 30000 ms is answered / timed out | Boundary value | `frontend/src/shared/api/client.test.ts` |
| waits for the completion up to the deadline: answered after 24999 / 25000 ms | Boundary value | `extension/background.test.js` |
| ends a read at once, as a cancellation, when its caller aborts it, or has already | Boundary value | `frontend/src/shared/api/client.test.ts` |
| lets a write take longer than the read deadline | Boundary value | `frontend/src/shared/api/client.test.ts` |
| job whose message was lost is published again after the unstarted limit | External failure (fault injection) | `src/whadio/processing/reliability/test_stalled_jobs.py` |
| job whose result was lost is published again only once past its running limit: at it, and 1 µs past it | External failure (fault injection), boundary value | `src/whadio/processing/reliability/test_stalled_jobs.py` |
| job lost on every publish fails its meeting with one notice after its attempts | Error handling | `src/whadio/processing/reliability/test_stalled_jobs.py` |
| job recovery failure is counted and the other jobs still run | Error handling | `src/whadio/scheduler/test_services.py` |
| published job is returned only once past the unstarted limit: 1 µs before, at and after it | Boundary value | `src/whadio/processing/test_repositories.py` |
| running job is returned with its attempts only once past its running limit, per job type | Boundary value | `src/whadio/processing/test_repositories.py` |

Run against the code before the fixes, the fault-injection, error-handling and at-the-deadline
tests fail, while the just-under-the-deadline ones pass on both versions, as they should. Each
part of the fixes is also covered by a test that fails when that part is removed: the caller's
signal in the web app's composed signal, the deadline on signing in, and reading the body under
the deadline.

The F9 tests are in Python. The lab's own, in `src/whadio/processing/reliability/`, run Processing
over the real job table in the test database, with test doubles for the broker, the worker and the
meetings: a broker that accepts every job and delivers none, and a worker that reports a job started
and never answers. They fail when recovery is skipped, when the publish guard is removed and when
the running limits of the two job types are swapped.

## Open issues

- F1, F3, F4, F5, F7 and F8 are open; each keeps its chain in
  [`scavenger-hunt.md`](scavenger-hunt.md).
- After F6, a write in the web app still has no client deadline, so an upload over a stalled
  connection keeps its progress state until the browser gives up. A deadline that resets on upload
  progress would bound it without breaking long uploads; `fetch` cannot report upload progress, so
  this needs `XMLHttpRequest`.
- F2 is checked by unit tests only. A run in Chrome with a real Google Meet recording through
  the offscreen document and a deliberately stalled `/complete`, which would show the local copy
  being saved before the worker stops, is still to be done.
- After F2, a `/complete` that the server takes more than 25 s to answer leaves the meeting on the
  server *and* a local copy on disk. Nothing is lost, but the user may upload the call twice.
  Answering `/complete` at once and assembling the recording in the background would remove the
  case, but that changes the API and belongs in its own issue.
- The service worker's lifetime still bounds the extension: its upload state lives only in memory,
  so a worker stopped for another reason (an event over 5 minutes, a browser update) loses the call.
  This needs its own issue.
- F2's deadline makes a stuck upload end, but the user still learns of the failure only at hang-up;
  telling them during the call is F3.
- After F9, the copies of a job that waited in the queue through a long outage are all delivered
  once a worker returns, oldest first. Each start counts an attempt, and a copy whose 24-hour audio
  link has expired fails at once, so after an outage of about 5 days or more the stale copies can
  use up the attempts and fail a meeting that a fresh copy would have processed. A message that
  names its attempt (below) would let Processing ignore the stale copies.
- After F9, a result names its job but not its attempt, so a late failure from a run that was
  handed back can count against the run that replaced it.
- After F9, `started_at` comes from the worker's clock, so a worker whose clock is off by more
  than a limit's margin gets its job handed back early or late.
- After F9, a lost message is noticed only after the unstarted limit. A check for a job that newer
  jobs of its queue have overtaken would notice it sooner.
- After F9, `attempts_started` in the admin job monitoring also counts publishes that no worker
  started, so it is the count against the retry limit rather than of starts.

## AI Usage

The F2 and F6 fixes, their tests and these sections were drafted with Claude Code
(Claude Opus 5.5) and reviewed by Zlata Tsepkalo.

The F9 fix, its tests and its sections were drafted with Claude Code and reviewed by Andrii
Shalaiev.
