import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { apiClient, normalizeApiOrigin, READ_TIMEOUT_MS } from "./client";
import { NETWORK_ERROR } from "./errors";
import { unwrap } from "./unwrap";

describe("normalizeApiOrigin", () => {
  test("removes a trailing slash", () => {
    // Act
    const origin = normalizeApiOrigin("https://api.example.com/");

    // Assert
    expect(origin).toBe("https://api.example.com");
  });

  test("removes several trailing slashes", () => {
    // Act
    const origin = normalizeApiOrigin("https://api.example.com///");

    // Assert
    expect(origin).toBe("https://api.example.com");
  });

  test("keeps a configured path prefix", () => {
    // Act
    const origin = normalizeApiOrigin("https://example.com/whadio/");

    // Assert
    expect(origin).toBe("https://example.com/whadio");
  });

  test("keeps slashes that are not trailing", () => {
    // Act
    const origin = normalizeApiOrigin("https://example.com/a//b");

    // Assert
    expect(origin).toBe("https://example.com/a//b");
  });

  test("removes a long trailing slash suffix", () => {
    // Arrange
    const configured = `https://api.example.com${"/".repeat(100_000)}`;

    // Act
    const origin = normalizeApiOrigin(configured);

    // Assert
    expect(origin).toBe("https://api.example.com");
  });

  test.for(["", undefined])("treats %s as the page's own origin", (configured) => {
    // Act
    const origin = normalizeApiOrigin(configured);

    // Assert
    expect(origin).toBe("");
  });
});

// Answers after `delay`, unless the request's signal aborts it first; an infinite delay never answers.
function answerAfter(delay: number, signal: AbortSignal | null | undefined): Promise<Response> {
  return new Promise((resolve, reject) => {
    const timer = Number.isFinite(delay)
      ? setTimeout(() => resolve(Response.json({ id: "u1" })), delay)
      : undefined;
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(signal.reason);
    });
  });
}

function serverAnsweringAfter(delay: number) {
  vi.stubGlobal(
    "fetch",
    vi.fn((_request: Request, init?: RequestInit) => answerAfter(delay, init?.signal)),
  );
}

// Lets `elapsed` pass on the fake clock and reports how the request ended.
async function outcomeAfter(request: Promise<unknown>, elapsed: number): Promise<unknown> {
  const outcome = request.then(
    () => "answered",
    (error: unknown) => error,
  );
  await vi.advanceTimersByTimeAsync(elapsed);
  return outcome;
}

describe("a server that stops answering", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  test("ends a read that gets no answer with a network error saying it timed out", async () => {
    // Arrange
    serverAnsweringAfter(Number.POSITIVE_INFINITY);

    // Act
    const outcome = await outcomeAfter(unwrap(apiClient.GET("/api/v1/users/me")), READ_TIMEOUT_MS);

    // Assert
    expect(outcome).toMatchObject({
      status: 0,
      code: NETWORK_ERROR,
      message: "The server did not answer in time. Try again.",
    });
  });

  test.for([
    [READ_TIMEOUT_MS - 1, "answered"],
    [READ_TIMEOUT_MS, "timed out"],
  ] as const)("a read answered after %i ms is %s", async ([delay, expected]) => {
    // Arrange
    serverAnsweringAfter(delay);

    // Act
    const outcome = await outcomeAfter(unwrap(apiClient.GET("/api/v1/users/me")), delay);

    // Assert
    expect(outcome === "answered" ? "answered" : "timed out").toBe(expected);
  });

  test("lets a write take longer than the read deadline", async () => {
    // Arrange
    serverAnsweringAfter(2 * READ_TIMEOUT_MS);

    // Act
    const outcome = await outcomeAfter(
      unwrap(
        apiClient.POST("/api/v1/workspaces", { body: { name: "Team", default_preset: "summary" } }),
      ),
      2 * READ_TIMEOUT_MS,
    );

    // Assert
    expect(outcome).toBe("answered");
  });
});
