import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, test } from "vitest";
import { ApiError } from "@/shared/api/errors";
import type { Schemas } from "@/shared/api/types";
import { errorBody } from "@/shared/testing/fixtures";
import { createTestQueryClient, TestProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { sessionQueries, useSignIn, useSignOut } from "./session";

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

describe("the signed-in user", () => {
  test("is the server's answer", async () => {
    // Arrange
    server.use(http.get("/api/v1/users/me", ({ response }) => response(200).json(USER)));

    // Act
    const user = await createTestQueryClient().query(sessionQueries.me());

    // Assert
    expect(user).toEqual(USER);
  });

  test("is nobody on a 401", async () => {
    // Arrange
    server.use(
      http.get("/api/v1/users/me", ({ response }) =>
        response(401).json(errorBody("UNAUTHENTICATED", "Sign in required")),
      ),
    );

    // Act
    const user = await createTestQueryClient().query(sessionQueries.me());

    // Assert
    expect(user).toBeNull();
  });

  test("stays unknown when the server fails", async () => {
    // Arrange
    server.use(
      http.get("/api/v1/users/me", ({ response }) =>
        response.untyped(new Response(null, { status: 503 })),
      ),
    );

    // Act
    const failure = createTestQueryClient().query(sessionQueries.me());

    // Assert
    await expect(failure).rejects.toBeInstanceOf(ApiError);
  });
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

  test("remembers the signed-in user", async () => {
    // Arrange
    server.use(
      http.post("/api/v1/sessions", ({ response }) =>
        response(201).json({ kind: "browser", expires_at: USER.created_at, user: USER }),
      ),
    );
    const { result, queryClient } = renderWithClient(useSignIn);

    // Act
    await result.current.mutateAsync(CREDENTIALS);

    // Assert
    expect(queryClient.getQueryData(sessionQueries.me().queryKey)).toEqual(USER);
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
    const rendered = renderWithClient(useSignOut);
    rendered.queryClient.setQueryData(sessionQueries.me().queryKey, USER);
    rendered.queryClient.setQueryData(["accounts", "mcp-keys"], { items: [] });
    return rendered;
  }

  test("clears the query cache", async () => {
    // Arrange
    const { result, queryClient } = signOut();

    // Act
    await result.current.mutateAsync().catch(() => undefined);

    // Assert
    expect(queryClient.getQueryData(["accounts", "mcp-keys"])).toBeUndefined();
  });

  test("forgets the signed-in user", async () => {
    // Arrange
    const { result, queryClient } = signOut();

    // Act
    await result.current.mutateAsync().catch(() => undefined);

    // Assert
    expect(queryClient.getQueryData(sessionQueries.me().queryKey)).toBeNull();
  });
});
