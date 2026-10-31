import { vi } from "vitest";

export function denySessionStorage() {
  vi.spyOn(globalThis, "sessionStorage", "get").mockImplementation(() => {
    throw new DOMException("Access is denied for this document.", "SecurityError");
  });
}
