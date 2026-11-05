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

Run against the code before the fixes, the fault-injection, error-handling and at-the-deadline
tests fail, while the just-under-the-deadline ones pass on both versions, as they should. Each
part of the fixes is also covered by a test that fails when that part is removed: the caller's
signal in the web app's composed signal, the deadline on signing in, and reading the body under
the deadline.

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

## AI Usage

The F2 and F6 fixes, their tests and these sections were drafted with Claude Code
(Claude Opus 5.5) and reviewed by Zlata Tsepkalo.
