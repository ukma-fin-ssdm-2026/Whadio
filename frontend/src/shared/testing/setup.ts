import type { TestingLibraryMatchers } from "@testing-library/jest-dom/matchers";
import * as matchers from "@testing-library/jest-dom/matchers";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, expect } from "vitest";
import { server } from "./server";

// jest-dom 7.0.1's "/vitest" entry augments Assertion<T>, which no longer type-checks against
// Vitest 5's Assertion<R, T>, so the matchers are registered and typed here instead.
declare module "vitest" {
  interface Matchers<R extends void | Promise<void> = void | Promise<void>, T = unknown>
    extends TestingLibraryMatchers<unknown, R> {}
}

expect.extend(matchers);

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});

// Testing Library only registers its own cleanup when Vitest globals are on, and they are off.
afterEach(() => {
  cleanup();
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});
