# Reliability Report

The findings come from [`scavenger-hunt.md`](scavenger-hunt.md), which also holds each one's
fault → error → failure chain and, in Stage 3, the choice between failing fast and failing safe.
Each fix below names who made it.

## Findings

| # | Finding | Category | Severity | Status |
|---|---|---|---|---|
| F1 | Job publish to RabbitMQ waits without a limit while holding a row lock | B, E | High | **Fixed** |
| F2 | Extension requests to the server have no deadline | B, E | High | **Fixed**; not yet checked with a real recording |
| F3 | A failed upload is given up without a log or a word to the user | D, A | Medium | Open |
| F4 | A recording that could not be saved vanishes in an unawaited listener | A, D | High | Open |
| F5 | Object storage calls can block a request for over half an hour | B, E | Medium | Open |
| F6 | The SPA's API client has no deadline | B | Low | **Fixed** |
| F7 | Signing out ignores whether the server ended the session | D | Low | Open |
| F8 | Asking which chunks the server holds fails silently | D | Low | Open |

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

### F1. Job publish to RabbitMQ waits without a limit while holding a row lock

Fixed by Denys Zabiiaka in `fix(#287): give the broker connection and publishes a deadline`.

**Before.** `src/whadio/shared/broker.py`: aio-pika waits forever by default, so a broker that never
confirms leaves `publish_next` inside its transaction, holding the job row's lock:

```python
await aio_pika.connect_robust(
    settings.url.get_secret_value(), client_properties={"connection_name": name}
)
...
await self._channel.default_exchange.publish(message, routing_key=queue, mandatory=True)
```

**After.** `src/whadio/shared/broker.py`: connecting and publishing both give up after
`WHADIO_BROKER__TIMEOUT` (ISO 8601 duration, default `PT10S`). `fail_fast=True` overrides the URL,
because `fail_fast=0` there would keep retrying past the timeout. The publish deadline also covers
the wait for a reconnecting connection, which aio-pika's own `timeout` argument does not.
`MessagePublisher` takes the timeout as a required keyword argument, so no caller can forget it:

```python
timeout: timedelta = Field(default=timedelta(seconds=10), gt=timedelta(0), ...)
...
await aio_pika.connect_robust(
    settings.url.get_secret_value(),
    timeout=settings.timeout.total_seconds(),
    fail_fast=True,
    client_properties={"connection_name": name},
)
...
async with asyncio.timeout(self._timeout.total_seconds()):
    await self._channel.default_exchange.publish(message, routing_key=queue, mandatory=True)
```

`src/whadio/workers/supervision/supervisor.py`: a blocked broker stops reading the connection, so
a worker whose result publish timed out would then wait forever for its consumer to be cancelled,
and never close the connection that returns the job. That wait now ends after the same timeout.
A worker publish that times out is no longer a failure of the job: the worker keeps the delivery
unsettled and publishes again with a backoff from 1 s up to 30 s, acknowledging the job only after
its result is confirmed. Stopping the worker instead returned the job to the queue on every
timeout, so six lost confirmations dead-lettered a valid job past its delivery limit of 5.

**Patterns.** A timeout on each attempt, then the retry `serve_publishing` already makes on its next
round, then the logging already there. The timeout goes innermost (§3.5): before it, the retry code
could never run, because no exception ever reached it.

**Failure and recovery.**

| | |
|---|---|
| Response | Fail-fast: a job must not count as published unless the broker confirmed it, so there is no safe value to return instead |
| What the user sees | The meeting stays "queued" while the broker is down, and processing starts once it is back |
| Recovery | Automatic: the transaction rolls back, the row lock is released, the failure is logged and the next round sends the job again |

## Reliability tests

The F2 and F6 fixes are in JavaScript, so their tests sit next to the code they test, as the
repository's Vitest convention asks, and not under `src/whadio/`. The extension's Vitest
configuration collects only `extension/*.test.js`. Each of those tests injects the failure through
a test double that replaces `fetch` and answers late or never. The F1 tests use test doubles for
an exchange and a queue that never answer, and a local TCP server that accepts a connection and
stays silent.

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
| publish the broker never confirms is logged as a failed round | Error handling | `src/whadio/processing/reliability/test_publish_deadline.py` |
| job goes out once a silent broker answers again | External failure (fault injection) | `src/whadio/processing/reliability/test_publish_deadline.py` |
| connect ends at the deadline with fail_fast off in the URL | External failure (fault injection) | `src/whadio/processing/reliability/test_publish_deadline.py` |
| connect that gave up leaves no retry task running | External failure (fault injection) | `src/whadio/processing/reliability/test_publish_deadline.py` |
| stopping the consumer ends when the broker never answers | External failure (fault injection) | `src/whadio/workers/supervision/test_supervisor.py` |
| job completes after more lost confirmations than its delivery limit | External failure (fault injection) | `src/whadio/workers/supervision/test_supervisor.py` |
| shutdown while confirmations are lost returns the job to the queue | Error handling | `src/whadio/workers/supervision/test_supervisor.py` |
| broker timeout of zero is refused | Boundary value | `src/whadio/processing/reliability/test_publish_deadline.py` |

Run against the code before the fixes, the fault-injection, error-handling and at-the-deadline
tests fail, while the just-under-the-deadline ones pass on both versions, as they should. Each
part of the fixes is also covered by a test that fails when that part is removed: the caller's
signal in the web app's composed signal, the deadline on signing in, and reading the body under
the deadline. The two F1 tests that serve a job hang and fail when the publish has no timeout, and
the F1 connect and consumer tests fail when `fail_fast=True` or the cancellation's deadline is
removed, and the lost-confirmation test fails when the worker's publish is not retried.

## Open issues

- F3, F4, F5, F7 and F8 are open; each keeps its chain in
  [`scavenger-hunt.md`](scavenger-hunt.md).
- F1 is checked with a test double only, not with a RabbitMQ that really raises a memory or disk
  alarm.
- After F1, a publish that times out can still reach the broker late. The next round then sends the
  job again, so a worker may run it twice; `handle` absorbs the second result.
- After F1, a worker blocked by the broker keeps retrying its publish while it holds the job. A
  block longer than the consumer timeout still makes RabbitMQ take the job back, and that counts
  towards the delivery limit.
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

## AI Usage

The F2 and F6 fixes, their tests and these sections were drafted with Claude Code
(Claude Opus 5.5) and reviewed by Zlata Tsepkalo.

The F1 fix, its tests and its sections were drafted with Claude Code (Claude Opus 5.5) and
reviewed by Denys Zabiiaka.
