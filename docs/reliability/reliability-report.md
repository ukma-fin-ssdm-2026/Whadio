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
| F5 | Object storage calls can block a request for over half an hour | B, E | High | **Fixed** |
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
Every resend of a result keeps one message ID, and Processing records the IDs it applied in
`processing_job.applied_result_ids` in the transaction that applies the result, then drops a
copy it has seen. Without that, a failure whose confirmation was lost and that was resent after
the next attempt had started failed the newer attempt and discarded its transcript. Cancelling
the consumer is no longer awaited past the deadline either: aiormq answers a cancelled call by
queueing a Channel.Close behind the frames the blocked broker does not read, so the worker leaves
that call to end with the connection it closes and reaps it afterwards.

**Patterns.** A timeout on each attempt, then the retry `serve_publishing` already makes on its next
round, then the logging already there. The timeout goes innermost (§3.5): before it, the retry code
could never run, because no exception ever reached it.

**Failure and recovery.**

| | |
|---|---|
| Response | Fail-fast: a job must not count as published unless the broker confirmed it, so there is no safe value to return instead |
| What the user sees | The meeting stays "queued" while the broker is down, and processing starts once it is back |
| Recovery | Automatic: the transaction rolls back, the row lock is released, the failure is logged and the next round sends the job again |

### F5. Object storage calls can block a request for over half an hour

Fixed by Andrii Shalaiev in `fix(#287): give object storage calls a timeout and turn off hidden
retries` and `fix(#287): retry storage reads and deletes with full-jitter backoff`.

**Before.** `src/whadio/shared/storage.py`: the clients get no `http_client`, so minio 7.2 builds
its own pool (`minio/api.py:169-180`) with `Timeout(connect=300, read=300)` and `Retry(total=5,
backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])`. A call to a store that stops
answering makes six attempts of up to 300 s each:

```python
def connect_s3_storage(settings: ObjectStorageSettings) -> S3ObjectStorage:
    return S3ObjectStorage(
        client=create_s3_client(settings, settings.endpoint_url),
        signer=create_s3_client(settings, settings.public_endpoint_url or settings.endpoint_url),
        bucket=settings.bucket,
    )
```

**After.** `src/whadio/shared/storage.py:35-45`: `WHADIO_STORAGE__TIMEOUT` (ISO 8601 duration,
default `PT5S`) bounds connecting and each read, and `WHADIO_STORAGE__ATTEMPTS` (default 3, from 1
to 5) bounds the tries of a read or a delete. `:176-202`: `bounded_pool` builds one pool for both
clients, with that timeout and no retries of its own, so every error reaches `S3ObjectStorage`. It
trusts the system CA store, which honours `SSL_CERT_FILE`, instead of the bundle minio's pool
loaded. `:78-96`, `:122-126`, `:144-156`: a read or a delete that fails with a transient error (a
connection or read error, or a 5xx answer) is tried again after a random wait; a 4xx such as
`AccessDenied` fails at once:

```python
return urllib3.PoolManager(
    timeout=urllib3.Timeout(connect=timeout, read=timeout),
    maxsize=10,
    cert_reqs="CERT_REQUIRED",
    retries=urllib3.Retry(total=False),
)
...


def wait(self, retry: int) -> None:
    self.sleep(self.uniform(0.0, min(_BACKOFF_CAP, _BACKOFF_BASE * 2.0**retry)))


...


def _retried[T](self, operation: str, call: Callable[[], T]) -> T:
    attempt = 1
    while True:
        try:
            return call()
        except (MinioException, urllib3.exceptions.HTTPError) as error:
            if not _is_transient(error):
                raise ObjectStorageError(f"{operation} failed") from error
            if attempt >= self._backoff.attempts:
                logger.warning("%s failed after %d attempts", operation, attempt)
                raise ObjectStorageError(f"{operation} failed") from error
        self._backoff.wait(attempt - 1)
        attempt += 1
```

`put` is still tried once. A multipart upload is not idempotent, and the extension already retries
every chunk, so retrying here as well would multiply the attempts. With `total=False`, urllib3 also
follows no redirects; the client is configured with its region, so S3 has no reason to send one.

Checked against the Compose SeaweedFS with the defaults: a 40 MiB random object went up as a
three-part upload in 0.15 s, came back identical in 0.04 s and was deleted in 0.002 s. Against a
local port that accepts and never answers, a get gave up after 15.46 s and a delete after 15.53 s.

**Patterns.** A timeout on each connection and read, innermost (§3.5), then bounded retries with
exponential backoff and full jitter, for the idempotent calls only and at one level only, then the
reactions already there: the API answers `503 INTEGRATION_UNAVAILABLE`, and the scheduler counts
the item as failed and tries it on its next pass. There is no circuit breaker: the API builds a
storage client for each request, so a breaker inside it would forget every failure, and one
storage operation already ends within about 16 s.

**Failure and recovery.**

| | |
|---|---|
| Response | Fail-fast in the API: an upload or a chunk that storage does not serve answers `503` within one storage operation's budget of about 16 s, and frees its thread and transaction. A capture completion whose read fails also runs a retried cleanup delete, so it answers within about 31.5 s at worst. Fail-safe in cleanup: a delete that fails keeps its row, so the recording is deleted later rather than forgotten |
| What the user sees | Nothing for a brief fault, which a retry absorbs. Otherwise an upload in the web app fails with "A service Whadio depends on is unavailable; try again later", and the extension retries the chunk and, if storage stays down, saves the call locally. Signing in no longer waits behind stalled storage calls |
| Recovery | Automatic for reads, deletes, chunks and cleanup: the retries within the call, then the extension's retries and the scheduler's next pass. The user repeats a failed upload in the web app |

## Reliability tests

The F2 and F6 fixes are in JavaScript, so their tests sit next to the code they test, as the
repository's Vitest convention asks, and not under `src/whadio/`. The extension's Vitest
configuration collects only `extension/*.test.js`. Each of those tests injects the failure through
a test double that replaces `fetch` and answers late or never. The F1 tests use test doubles for
an exchange and a queue that never answer, and a local TCP server that accepts a connection and
stays silent. The F5 tests use a local TCP server that accepts and never answers, or hangs up at
once, and a test double for the connection pool that times out or answers with a chosen status.

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
| stopping the consumer ends when closing its channel stalls too | External failure (fault injection) | `src/whadio/workers/supervision/test_supervisor.py` |
| job completes after more lost confirmations than its delivery limit | External failure (fault injection) | `src/whadio/workers/supervision/test_supervisor.py` |
| job is acknowledged only after a final result with lost confirmations | External failure (fault injection) | `src/whadio/workers/supervision/test_supervisor.py` |
| every resend of a result keeps its ID | Error handling | `src/whadio/workers/supervision/test_supervisor.py` |
| resent failure leaves the next attempt running (transcription and notes) | Error handling | `src/whadio/processing/test_services.py` |
| failure of the next attempt under a new ID is applied | Error handling | `src/whadio/processing/test_services.py` |
| result without a valid message ID is rejected without requeue | Error handling | `src/whadio/processing/test_consumer.py` |
| shutdown while confirmations are lost returns the job to the queue | Error handling | `src/whadio/workers/supervision/test_supervisor.py` |
| broker timeout of zero is refused | Boundary value | `src/whadio/processing/reliability/test_publish_deadline.py` |
| call to a failing store is given up after its attempts: a get that gets no answer, a delete whose connection is dropped | External failure (fault injection) | `src/whadio/shared/reliability/test_storage_deadline.py` |
| get that times out on every attempt logs one warning without the key | Error handling | `src/whadio/shared/reliability/test_storage_deadline.py` |
| request is sent once when a repeat is futile or unsafe: a get refused with `AccessDenied`, a put answered `503` | Error handling | `src/whadio/shared/reliability/test_storage_deadline.py` |
| get that succeeds on the last attempt returns the object, with 1, 3 and 5 attempts | Boundary value | `src/whadio/shared/reliability/test_storage_deadline.py` |
| get that would succeed one attempt later raises, with 1, 3 and 5 attempts | Boundary value | `src/whadio/shared/reliability/test_storage_deadline.py` |
| wait before retry n is drawn up to a quarter second doubled n times | Boundary value | `src/whadio/shared/reliability/test_storage_deadline.py` |
| wait stops growing at two seconds | Boundary value | `src/whadio/shared/reliability/test_storage_deadline.py` |
| storage settings bound the timeout and the attempts | Boundary value | `src/whadio/shared/reliability/test_storage_deadline.py` |
| call answered 5xx recovers on its last attempt: get and delete, for `S3Error` and `ServerError` | Error handling | `src/whadio/shared/reliability/test_storage_deadline.py` |
| call answered 5xx every time gives up after its attempts: get and delete, for `S3Error` and `ServerError` | Boundary value | `src/whadio/shared/reliability/test_storage_deadline.py` |
| pool waits the timeout to connect and for each read, and retries nothing | Error handling | `src/whadio/shared/reliability/test_storage_deadline.py` |

Run against the code before the fixes, the fault-injection, error-handling and at-the-deadline
tests fail, while the just-under-the-deadline ones pass on both versions, as they should. Each
part of the fixes is also covered by a test that fails when that part is removed: the caller's
signal in the web app's composed signal, the deadline on signing in, and reading the body under
the deadline. The two F1 tests that serve a job hang and fail when the publish has no timeout, and
the F1 connect and consumer tests fail when `fail_fast=True` or the cancellation's deadline is
removed, and the lost-confirmation test fails when the worker's publish is not retried. Each F5
test fails when the part it guards is broken: the pool left with urllib3's default retries (12
connections instead of 3), no pool given to the client (the get hangs until a 60 s limit stops it),
a 4xx treated as transient, the retry removed, one attempt too many, a fixed or uncapped wait, the
warning removed, the put retried, either 5xx branch of `_is_transient` returning False, and no
connect timeout.

## Open issues

- F3, F4, F7 and F8 are open; each keeps its chain in
  [`scavenger-hunt.md`](scavenger-hunt.md).
- F1 is checked with a test double only, not with a RabbitMQ that really raises a memory or disk
  alarm.
- After F1, a publish that times out can still reach the broker late. The next round then sends the
  job again, so a worker may run it twice; `handle` absorbs the second result.
- After F1, a worker blocked by the broker keeps retrying its publish while it holds the job. A
  block longer than the consumer timeout still makes RabbitMQ take the job back, and that counts
  towards the delivery limit.
- After F5, the timeout bounds each connection and each read, not the whole call: a store that
  sends a few bytes every few seconds keeps a call going.
- After F5, a `put` is tried once, so a brief fault fails an upload from the web app, which the
  user then repeats.
- After F5, minio raises `InvalidResponseError` for an error answer without an XML body, such as a
  `502` from a proxy in front of the store, and keeps its status private, so that answer is not
  retried.
- After F5, the retention pass carries on after a storage failure, so with storage down each due
  recording costs about 16 s, and email delivery, which runs after the pass, waits for all of them.
- After F5, a capture assembly that fails can leave its object behind: when deleting it fails too,
  `_discard` in `src/whadio/capture/services.py` only logs it, and no row refers to the object, so
  no later pass deletes it.
- After F5, a capture completion against a store that does not answer runs a retried read and then
  `_discard`'s retried delete: about 31.5 s at worst, measured 30.94 s over six connections. The
  extension's 25 s deadline on `/complete` fires first, and the extension then saves the call
  locally; the capture stays open on the server.
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

The F5 fix, its tests and its sections were drafted with Claude Code and reviewed by Andrii
Shalaiev.

## Bonuses

### Bonus 1: bounded retries with exponential backoff and full jitter

F5 retries one idempotent external call and composes the retry with the timeout as §3.5 orders
them: the timeout bounds each attempt, and the retry wraps the attempts.

- **The call.** A read or a delete in object storage, `S3ObjectStorage.get` and `.delete`
  (`src/whadio/shared/storage.py:122-126`), through `_retried` (`:144-156`). Both are safe to
  repeat: deleting an object that is already gone succeeds. Only a transient error is retried: a
  connection or read error, or a 5xx answer.
- **The formula.** Before retry *n*, counted from 0, the call sleeps a time drawn uniformly from 0
  to min(2 s, 0.25 s × 2ⁿ) (`Backoff.wait`, `:86-88`), so callers that failed together do not
  retry together.
- **The defaults.** 3 attempts, and 5 s for connecting and for each read.
- **The bound.** Against a store that does not answer, a call ends after at most 3 × 5 s of
  waiting and 0.25 + 0.5 s of backoff, about 15.75 s; measured, 15.46 s for a get and 15.53 s for
  a delete. That is under the extension's 25 s deadline, so the server answers a stalled chunk
  before the extension gives up on it. A capture completion whose read fails also runs a cleanup
  delete, about 31.5 s at worst, so there the extension's deadline fires first and the call is
  saved locally.
- **After the last attempt.** One warning, such as "Reading an object failed after 3 attempts",
  that never names the object key, then `ObjectStorageError`: the API answers
  `503 INTEGRATION_UNAVAILABLE`, and the scheduler keeps the item for its next pass.
- **The tests.** `test_wait_before_retry_n_is_drawn_up_to_a_quarter_second_doubled_n_times` and
  `test_wait_stops_growing_at_two_seconds` prove the formula and the cap;
  `test_call_to_a_failing_store_is_given_up_after_its_attempts`,
  `test_get_that_succeeds_on_the_last_attempt_returns_the_object` and
  `test_get_that_would_succeed_one_attempt_later_raises` and
  `test_call_answered_5xx_every_time_gives_up_after_its_attempts` prove the number of attempts;
  `test_get_that_times_out_on_every_attempt_logs_one_warning_without_the_key` proves the reaction
  after the last one; all in `src/whadio/shared/reliability/test_storage_deadline.py`.
