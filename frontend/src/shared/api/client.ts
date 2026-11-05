import createClient from "openapi-fetch";
import { serializeBody } from "./body";
import type { paths } from "./schema.gen";

export function normalizeApiOrigin(origin: string | undefined): string {
  const configuredOrigin = origin ?? "";
  let end = configuredOrigin.length;

  while (end > 0 && configuredOrigin[end - 1] === "/") {
    end -= 1;
  }

  return configuredOrigin.slice(0, end);
}

export const API_ORIGIN = normalizeApiOrigin(import.meta.env.VITE_API_ORIGIN);

// Reads only: a recording upload can take minutes, and a write given up here may still land on the
// server, so retrying it could repeat it.
export const READ_TIMEOUT_MS = 30_000;

// A plain timer rather than AbortSignal.timeout, whose timer the tests' fake clock cannot move. The
// caller's signal is kept, so a query cancelled by React Query still aborts at once.
function withReadDeadline(request: Request): RequestInit | undefined {
  if (request.method !== "GET") return undefined;
  const deadline = new AbortController();
  setTimeout(
    () => deadline.abort(new DOMException("The server did not answer in time.", "TimeoutError")),
    READ_TIMEOUT_MS,
  );
  return { signal: AbortSignal.any([request.signal, deadline.signal]) };
}

export const apiClient = createClient<paths>({
  // openapi-fetch builds a Request, and outside a browser (Node under Vitest) Request rejects
  // a relative URL, so the same-origin case names the page's origin explicitly.
  baseUrl: API_ORIGIN || window.location.origin,
  // "include" so the session cookie also reaches an API on another origin (VITE_API_ORIGIN).
  credentials: "include",
  bodySerializer: serializeBody,
  // openapi-fetch otherwise keeps the fetch it saw at import, before MSW patches it in tests.
  fetch: (request) => globalThis.fetch(request, withReadDeadline(request)),
});
