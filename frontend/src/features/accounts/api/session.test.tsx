import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { denySessionStorage } from "@/shared/testing/deny-storage";
import { createTestQueryClient, TestProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { readSignedInUser, storeSignedInUser } from "../session-storage";
import { useSignIn, useSignOut } from "./session";

const USER: Schemas["UserRead"] = {
  id: "member",
  email: "member@example.com",
  name: "Demo Member",
  is_administrator: false,
  created_at: "2026-10-25T10:00:00Z",
};

const CREDENTIALS = { email: "member@example.com", password: "test-password" };

function renderWithClient<T>(hook: () => T) {
  const queryClient = createTestQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <TestProviders queryClient={queryClient}>{children}</TestProviders>
  );
  return { ...renderHook(hook, { wrapper }), queryClient };
}

beforeEach(() => {
  sessionStorage.clear();
});

describe("sign-in", () => {
  test("asks for a browser session with the credentials", async () => {
    // Arrange
    const bodies: unknown[] = [];
    server.use(
      http.post("/api/v1/sessions", async ({ request, response }) => {
        bodies.push(await request.json());
        return response(201).json({ kind: "browser", expires_at: USER.created_at, user: USER });
      }),
    );
    const { result } = renderWithClient(useSignIn);

    // Act
    await result.current.mutateAsync(CREDENTIALS);

    // Assert
    expect(bodies).toEqual([{ ...CREDENTIALS, kind: "browser" }]);
  });

  test("keeps the signed-in user for the tab", async () => {
    // Arrange
    server.use(
      http.post("/api/v1/sessions", ({ response }) =>
        response(201).json({ kind: "browser", expires_at: USER.created_at, user: USER }),
      ),
    );
    const { result } = renderWithClient(useSignIn);

    // Act
    await result.current.mutateAsync(CREDENTIALS);

    // Assert
    expect(readSignedInUser()).toEqual({ id: USER.id, email: USER.email, name: USER.name });
  });
});

describe.for([
  ["succeeds", 204],
  ["fails", 503],
] as const)("sign-out that %s", ([, status]) => {
  function signOut() {
    server.use(
      http.delete("/api/v1/sessions/current", ({ response }) =>
        response.untyped(new Response(null, { status })),
      ),
    );
    storeSignedInUser(USER);
    const rendered = renderWithClient(useSignOut);
    rendered.queryClient.setQueryData(["accounts", "mcp-keys"], { items: [] });
    return rendered;
  }

  test("clears the query cache", async () => {
    // Arrange
    const { result, queryClient } = signOut();

    // Act
    await result.current.mutateAsync().catch(() => undefined);

    // Assert
    expect(queryClient.getQueryCache().getAll()).toEqual([]);
  });

  test("forgets the signed-in user", async () => {
    // Arrange
    const { result } = signOut();

    // Act
    await result.current.mutateAsync().catch(() => undefined);

    // Assert
    expect(readSignedInUser()).toBeNull();
  });
});

describe("when storage is denied", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("signing in still succeeds", async () => {
    // Arrange
    server.use(
      http.post("/api/v1/sessions", ({ response }) =>
        response(201).json({ kind: "browser", expires_at: USER.created_at, user: USER }),
      ),
    );
    const { result } = renderWithClient(useSignIn);
    denySessionStorage();

    // Act
    const session = await result.current.mutateAsync(CREDENTIALS);

    // Assert
    expect(session.user).toEqual(USER);
  });

  test("signing out still clears the query cache", async () => {
    // Arrange
    server.use(http.delete("/api/v1/sessions/current", ({ response }) => response(204).empty()));
    const { result, queryClient } = renderWithClient(useSignOut);
    queryClient.setQueryData(["accounts", "mcp-keys"], { items: [] });
    denySessionStorage();

    // Act
    await result.current.mutateAsync().catch(() => undefined);

    // Assert
    expect(queryClient.getQueryCache().getAll()).toEqual([]);
  });
});
