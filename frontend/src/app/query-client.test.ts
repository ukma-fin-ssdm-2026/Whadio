import { MutationObserver, type QueryClient } from "@tanstack/react-query";
import { describe, expect, test, vi } from "vitest";
import { ApiError } from "@/shared/api/errors";
import { createQueryClient, retryUnlessClientError } from "./query-client";

const apiError = (status: number, code: ApiError["code"]) =>
  new ApiError({ status, code, message: "Request failed" });

const SESSION_EXPIRED = apiError(401, "UNAUTHENTICATED");

const failQuery = (client: QueryClient, error: Error) =>
  client
    .query({ queryKey: ["failing"], queryFn: () => Promise.reject(error), retry: false })
    .catch(() => undefined);

const failMutation = (client: QueryClient, error: Error) =>
  new MutationObserver(client, { mutationFn: () => Promise.reject(error) })
    .mutate()
    .catch(() => undefined);

describe("an expired session", () => {
  test("in a query calls the unauthorized handler", async () => {
    // Arrange
    const onUnauthorized = vi.fn();
    const client = createQueryClient({ onUnauthorized });

    // Act
    await failQuery(client, SESSION_EXPIRED);

    // Assert
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  test("in a mutation calls the unauthorized handler", async () => {
    // Arrange
    const onUnauthorized = vi.fn();
    const client = createQueryClient({ onUnauthorized });

    // Act
    await failMutation(client, SESSION_EXPIRED);

    // Assert
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
});

test.for([
  ["wrong credentials", apiError(401, "INVALID_CREDENTIALS")],
  ["a forbidden request", apiError(403, "INSUFFICIENT_ROLE")],
  ["a server error", apiError(500, "INTERNAL_ERROR")],
] as const)("%s leaves the session alone", async ([, error]) => {
  // Arrange
  const onUnauthorized = vi.fn();
  const client = createQueryClient({ onUnauthorized });

  // Act
  await failMutation(client, error);

  // Assert
  expect(onUnauthorized).not.toHaveBeenCalled();
});

describe("query retry", () => {
  test.for([400, 401, 403, 404, 422])("gives up at once on a %i", (status) => {
    // Act
    const retried = retryUnlessClientError(0, apiError(status, "VALIDATION_ERROR"));

    // Assert
    expect(retried).toBe(false);
  });

  test.for([
    ["a server error", apiError(503, "INTEGRATION_UNAVAILABLE")],
    ["an unreachable server", apiError(0, "NETWORK_ERROR")],
    ["an unexpected exception", new TypeError("Failed")],
  ] as const)("tries again after %s", ([, error]) => {
    // Act
    const retried = retryUnlessClientError(0, error);

    // Assert
    expect(retried).toBe(true);
  });

  test("stops after two retries", () => {
    // Act
    const retried = retryUnlessClientError(2, apiError(503, "INTEGRATION_UNAVAILABLE"));

    // Assert
    expect(retried).toBe(false);
  });
});
