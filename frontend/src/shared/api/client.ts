import createClient from "openapi-fetch";
import type { paths } from "./schema.gen";

export const API_ORIGIN = import.meta.env.VITE_API_ORIGIN ?? "";

export const apiClient = createClient<paths>({
  // openapi-fetch builds a Request, and outside a browser (Node under Vitest) Request rejects
  // a relative URL, so the same-origin case names the page's origin explicitly.
  baseUrl: API_ORIGIN || window.location.origin,
  // "include" so the session cookie also reaches an API on another origin (VITE_API_ORIGIN).
  credentials: "include",
  // openapi-fetch otherwise keeps the fetch it saw at import, before MSW patches it in tests.
  fetch: (request) => globalThis.fetch(request),
});
