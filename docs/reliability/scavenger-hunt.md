# Resilience Scavenger Hunt

Starting point: `main` at `8735c26`. Scope: the backend (`src/whadio/`: API, modules, workers and
scheduler) and the SPA's API client (`frontend/src/shared/api/`), as the issue sets it, plus the
browser extension (`extension/`), which uploads every recording and so carries most of the risk of
losing one.

Ten findings, each with its category from the hunt's checklist: A error handling · B external
dependencies · C input validation · D silent failures · E performance and blocking.

## Stage 1: Findings

### F1. Job publish to RabbitMQ waits without a limit while holding a row lock (B, E)

`src/whadio/shared/broker.py:23`, `:54`, called from `src/whadio/processing/services.py:196`,
`:205` (`publish_next`):

```python
async def connect(settings: BrokerSettings, *, name: str) -> AbstractRobustConnection:
    return await aio_pika.connect_robust(
        settings.url.get_secret_value(), client_properties={"connection_name": name}
    )


...
await self._channel.default_exchange.publish(message, routing_key=queue, mandatory=True)
```

```python
job = await self._jobs.next_unpublished()  # SELECT ... FOR UPDATE SKIP LOCKED
...
await publisher.publish(request)  # inside the same database transaction
```

**Why it is dangerous.** In aio-pika 10.2, both `connect_robust(timeout=None)` and
`Exchange.publish(timeout=None)` wait forever by default. A broker that blocks its publishers (a
memory or disk alarm sends `connection.blocked`), or a connection that goes quiet, never confirms
the publish. The await never returns and never raises. Meanwhile `publish_next` keeps its database
transaction open and holds the job row's lock.

**Potential impact.** `serve_publishing` is built to log a failed publish and retry it next round,
but no exception ever reaches that `except`. Publishing stops for the whole web instance. Every
meeting uploaded afterwards stays "queued" with no error anywhere, a pooled database connection
stays tied up, and the lock lasts until the process restarts.

### F2. Extension requests to the server have no deadline (B, E)

`extension/api.js:31`:

```js
const response = await fetch(`${server}/api/v1${path}`, init);
```

**Why it is dangerous.** `fetch` has no timeout of its own. On a half-open connection (Wi-Fi
handover, a proxy that drops the flow, a laptop that slept) the request can stay pending for good.
`Upload.send()` retries only when `api()` *throws*, and a pending request never throws.

**Potential impact.** All chunks go through a single promise chain (`upload.queue`), so one stuck
`PUT` stops the whole upload. At hang-up, `finish()` does `await this.queue` and never gets past it,
which means neither `/complete` nor the `saveLocally` fallback runs. The call's audio ends up
neither on the server nor on disk. It is lost.

### F3. A failed upload is given up without a log or a word to the user (D, A)

`extension/background.js:174`, `:221`, `Upload.send()` and `Upload.finish()`:

```js
} catch (failure) {
  if (shouldGiveUp(failure, attempt)) {
    this.failed = true;
    return;
  }
```

```js
} catch {
  // Saved below instead, so the call is not lost.
}
```

**Why it is dangerous.** After five attempts, or at once on a 401 or 404, the upload is marked
failed and the `ServerError` (its status and the server's message) is thrown away. Completing the
capture can fail the same way without a trace.

**Potential impact.** The user keeps recording, believing the call is going to the server, and only
finds a `.webm` download at the end. When someone reports that a meeting never showed up, the
service worker console holds nothing that tells an expired session (401), a deleted capture (404)
and a network outage apart.

### F4. A recording that could not be saved vanishes in an unawaited listener (A, D)

`extension/background.js:262`, the recording port's `onDisconnect` listener:

```js
port.onDisconnect.addListener(async () => {
  ...
  await upload.finish();
  await closeOffscreenIfIdle();
});
```

**Why it is dangerous.** Chrome does not await event listeners. When `finish()` falls back to
`saveLocally` and that throws (downloads blocked by policy, the offscreen document failed to open,
no disk space), the rejection goes nowhere. `closeOffscreenIfIdle()` is skipped too.

**Potential impact.** This is the last safety net for the recording, and when it fails the user is
not told and nothing is logged. The offscreen document can also stay open.

### F5. Object storage calls can block a request for over half an hour (B, E)

`src/whadio/shared/storage.py:113`:

```python
return Minio(
    f"{endpoint_url.host}:{endpoint_url.port}",
    ...
    http_client=http_client,   # None in production
)
```

**Why it is dangerous.** Without an `http_client`, MinIO builds its own pool:
`Timeout(connect=300, read=300)` and `Retry(total=5)` (minio 7.2, `api.py`). Every `put`, `get`
and `delete` runs in `asyncio.to_thread`: in API request handlers for an upload, a capture chunk
and the capture's assembly, which delete only to clean up after a failure, and in the scheduler.
Deleting a meeting only queues its recording, and the scheduler deletes it. If storage does not
answer, one call can make six attempts of up to 300 s each, and a multipart upload more.

**Potential impact.** The HTTP request hangs until nginx or the browser gives up. Each stuck call
holds a thread from the default executor and a database transaction. A few of them exhaust the
pool, and then password hashing, which uses the same executor, stalls as well, so sign-ins hang too.
The scheduler runs its jobs one after another, so one stuck delete also holds up retention and the
email delivery that follows it.

### F6. The SPA's API client has no deadline (B)

`frontend/src/shared/api/client.ts:26`:

```ts
fetch: (request) => globalThis.fetch(request),
```

**Why it is dangerous.** This is the same gap as F2, for every call the web app makes.

**Potential impact.** On a stalled connection, pages show their loading state indefinitely instead
of an error with a retry button. It is lower in severity than F2 because nothing is lost: reloading
the page recovers.

### F7. Signing out ignores whether the server ended the session (D)

`extension/api.js:83`:

```js
await api("DELETE", "/sessions/current").catch(() => {});
```

**Why it is dangerous.** If the request fails, the local token is still removed, but the server
never revokes the session. Nothing records that.

**Potential impact.** An extension session stays valid on the server for up to 24 hours after the
user believes they signed out. The token lived only in `chrome.storage.session` and is deleted, so
an attacker would need a copy taken earlier. That makes the risk low.

### F8. Asking which chunks the server holds fails silently (D)

`extension/background.js:206`, `Upload.syncReceived()`:

```js
const found = await api("GET", `/captures/${this.capture.id}`).catch(() => null);
```

**Why it is dangerous.** Returning `null` is the right *behaviour*: without the answer, the next
retry re-sends chunks and the server accepts the duplicates idempotently. But the failure is not
logged.

**Potential impact.** Diagnosis only. A series of failed retries leaves no record of whether
`GET` failed as well as `PUT`.

### F9. A published job whose message or result is lost is never finished (B, D)

Added from #294. `src/whadio/processing/services.py:196`, `:205-206` (`publish_next` and its call
to `mark_published`), and `src/whadio/processing/repositories.py:78-86` (`next_unpublished`):

```python
job = await self._jobs.next_unpublished()
...
await publisher.publish(request)
await self._jobs.mark_published(job.job_id, now, context)
```

```python
select(ProcessingJob)
.where(ProcessingJob.status == JobStatus.QUEUED, ProcessingJob.published_at.is_(None))
```

**Why it is dangerous.** Once `published_at` is set, the publisher never looks at the job again,
and nothing else does. If the message is lost (a purged queue, a recreated broker volume), the row
stays `queued` with `published_at` set. If a worker reported `job_started` and its result never
came (a host that did not come back, a result queue that was deleted), the row stays `running`.
The queues' delivery limit covers a worker that crashes while it holds the message; it does not
cover a message that is gone.

**Potential impact.** The meeting shows "queued" or "processing" for ever. No error is logged and
the uploader is never notified. Processing refuses to queue the meeting's transcription again while
the job is unfinished, so nothing retries it (NFR-014).

### F10. An interrupted local download is treated as a successful save (A, D)

Found while fixing F4. In `extension/background.js`, the original `downloaded` helper resolved
on any terminal state:

```js
if (delta.id === downloadId && delta.state && delta.state.current !== "in_progress") {
  chrome.downloads.onChanged.removeListener(listener);
  resolve();
}
```

**Why it is dangerous.** Chrome reports both `complete` and `interrupted`; interruption is not
successful persistence. A cancellation, disk error or browser policy can interrupt a download
after `chrome.downloads.download()` successfully returns its ID. The helper also registered too
late to observe a very fast terminal event, potentially waiting forever.

**Potential impact.** The extension releases the Blob and, after F4, removes its durable recovery
copy despite the missing/incomplete file. If uploading also failed, the recording can be lost.
This is separate from F4: no promise has to reject for F10 to occur.

### Reviewed and kept

These look like the checklist's anti-patterns but are deliberate boundaries:

- `except Exception` in `processing/consumer.py` (`serve_publishing`, `on_result`,
  `on_dead_letter`), `workers/supervision/runners.py` and `supervisor.py`. Each sits at the top of
  a long-running loop or task, logs with `logger.exception`, and turns the failure into a retry, a
  requeue or a failed-job result. A narrower catch there would let one bad message crash the
  consumer.
- `except BaseException` in `api/meetings/routes.py` and `capture/services.py`. They delete the
  half-written object under `asyncio.shield` and re-raise, so cancellation is cleaned up and not
  swallowed.
- SMTP, Ollama, Anthropic, the ASR worker's recording fetch and PostgreSQL all already have
  explicit timeouts, and their errors are mapped to typed failures.
- The scheduler catches `SQLAlchemyError` per cleanup job, logs it and carries on with the next
  job, so one failing cleanup does not stop the others. The workers parse every job message with
  pydantic in `workers/supervision/supervisor.py`, and log and reject a malformed one without
  requeuing it, so it cannot loop.
- Input validation (C): no finding. Request bodies, query parameters and job messages are parsed
  by pydantic models at the boundary, with types, ranges and required fields declared on the
  fields, so a missing or malformed value is refused before it reaches a service.

## Stage 2: Fault → error → failure

Most of these are faults whose error has not yet reached a failure. In those cases the "failure"
column describes what a user or another system sees once the chain completes.

| # | Fault (in the code) | Error (wrong internal state) | Failure (seen outside) | Severity |
|---|---|---|---|---|
| F1 | `publish()` and `connect_robust()` called without `timeout` | The publisher coroutine waits for a confirm that never comes; its transaction stays open and the job row stays locked | No new meeting gets transcribed or summarised; they all show "queued" and no error is logged | **High** |
| F2 | `fetch()` called without an abort signal | One chunk `PUT` stays pending; `upload.queue` and `finish()` wait on it | The recording reaches neither the server nor the user's disk: the call's audio is lost | **High** |
| F3 | `catch` sets `failed = true` and drops the error | The upload has stopped, but the user and the logs do not know | The user records a whole call believing it is being uploaded; support cannot tell why it failed | **Medium** |
| F4 | An `async` listener's rejection is not handled | `saveLocally` failed; the offscreen document may stay open | A recording that failed to upload is not saved either, with no message and no log | **High** |
| F5 | MinIO's default 300 s timeouts and 5 retries | Request handlers, executor threads and the scheduler wait on storage for up to 30 minutes | Uploads and captures hang, and so does the scheduler's cleanup; under load, sign-ins stall too because the thread pool is exhausted | **High** |
| F6 | The SPA's `fetch` has no deadline | A query stays in its loading state | A page spins with no error or retry offered | **Low** |
| F7 | `.catch(() => {})` around session revocation | The server-side session is still active | The extension session stays usable for up to 24 h after sign-out | **Low** |
| F8 | `.catch(() => null)` without a log | The retry proceeds without knowing what the server holds | No user-visible failure, as the duplicates are absorbed; a support engineer cannot tell from the logs whether the status request failed | **Low** |
| F9 | No lease or timeout on a published or running job | A `queued` row with `published_at` set, or a `running` row, whose message or result is gone | The meeting stays queued or processing for ever, with no notice, and its transcription cannot be queued again | **Medium** |
| F10 | Every terminal download state is accepted as success; observation starts after creation | An interrupted save is marked successful, or an early terminal event is missed | The last local copy is discarded without a complete file, or recovery stays stuck | **High** |

F5 is High because a few stalled calls fill the database pool and the executor that Argon2 sign-in
hashing shares, and a single one stalls the scheduler's sequential tick.

## Stage 3: Remediation

For each finding chosen for fixing, the deciding question is which is worse in that place: a wrong
answer or no answer (§3.1). The fixes, before and after, are in
[`reliability-report.md`](reliability-report.md).

| # | Worse here | Response | Patterns, in the order of §3.5 | Fixed by |
|---|---|---|---|---|
| F1 | No answer: one publish that never returns stops publishing for the whole instance, with the row locked and nothing logged | **Fail-fast.** A publish the broker does not confirm in time raises, the transaction rolls back and the job stays unpublished | Timeout per attempt → retry on the next round (existing) → logging (existing) | Denys, `fix(#287): give the broker connection and publishes a deadline` |
| F2 | No answer: a chunk that waits forever loses the whole call | **Fail-safe.** A request that runs out is retried; once retries are spent the call is saved locally | Timeout per request → retry with backoff (existing) → local file fallback (existing) | Zlata, `fix(#287): give the extension's requests a deadline` |
| F4 | Losing the last local copy is worse than waiting for a download retry | **Fail-safe.** Persist the completed fallback recording before downloading, handle finalization failures, and retain failed saves for Retry download or Discard | Durable fallback → explicit error handling and sanitized warning → user-triggered retry or confirmed discard → cleanup in `finally` | `fix(#287): retain recordings when local saving fails` |
| F5 | No answer: a call that waits half an hour holds a transaction and an executor thread, and stops the scheduler | **Fail-fast** in the API: an upload or a chunk that storage does not serve answers `503` within one storage operation's budget of about 16 s; a capture completion whose read fails also runs a cleanup delete, about 31.5 s at worst, so the extension's 25 s deadline fires first and the call is saved locally. **Fail-safe** in cleanup: a delete that fails keeps its row for the next pass | Timeout per connection and read → bounded retry with full jitter, for reads and deletes only → no circuit breaker: the API builds a storage client for each request, so a breaker would forget every failure, and one storage operation already ends within about 16 s → `503` (existing) / next scheduler pass (existing) | Andrii, `fix(#287): give object storage calls a timeout and turn off hidden retries` |
| F6 | No answer for reads: a page loads forever. A wrong answer for writes: giving up on an upload that still lands invites a duplicate | **Fail-fast** for reads: the read ends with an error that says it timed out, and the page shows it instead of loading forever. Writes keep no client deadline | Timeout on reads → retry by React Query (existing) → clear error message | Zlata, `fix(#287): give the web app's reads a deadline` |
| F9 | No answer: a meeting that waits for ever is worse than one that fails with a notice and can be uploaded again | **Fail-safe** while attempts remain: the job is published again. **Fail-fast** at the cap: the meeting is failed | Timeout per job (unstarted, or running per type) → bounded retry: the job goes back to the publisher, 5 attempts → no circuit breaker: the scheduler only looks at the database, and a republished job waits in the queue instead of calling anything → degradation: a failed meeting with a notice, which the member can upload again | Andrii, `fix(#294): return published jobs that no worker started to the queue` |

| F10 | A wrong answer: reporting an interrupted download as saved discards the last copy of the recording | **Fail-safe.** Only `complete` confirms a save; an interrupted download leaves the recording available for Retry download or Discard through F4's recovery flow | Observe before starting → reconcile download history → validate the terminal state → retained fallback and manual retry (F4) | Valeriia, `fix(#287): retain recovery copies after interrupted downloads` |

## Stage 4: The finding to present

**F2: the extension can lose a whole call when the network goes quiet.**

- **Fault:** `fetch()` in `extension/api.js` is called without an abort signal or deadline.
- **Error:** one chunk upload stays pending forever. The upload queue behind it, and the
  hang-up handler's `await this.queue`, wait on it.
- **Failure:** the user ends the call and gets nothing: the meeting is not in Whadio, and the
  promised local `.webm` is never downloaded, because the fallback sits behind the stuck promise.
- **Fix:** every extension request, `/complete` included, now gives up after 25 s, before Chrome
  stops the service worker, so the stuck chunk is retried and, if the server stays silent, the
  call is saved locally. See
  [`reliability-report.md`](reliability-report.md#f2-extension-requests-to-the-server-have-no-deadline).

## AI Usage

The findings and this report were drafted with Claude Code (Claude Opus 5.5) and
reviewed by the team.

F4, F10s's remediation and tests were prepared with OpenAI Codex (GPT-6.1); reviewed by Valeriia.
