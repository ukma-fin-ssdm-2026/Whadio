import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { createTestQueryClient, TestProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { currentUserQuery } from "./current-user";
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

  test("remembers the signed-in user without asking the API again", async () => {
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
    expect(queryClient.getQueryData(currentUserQuery().queryKey)).toEqual(USER);
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
    rendered.queryClient.setQueryData(currentUserQuery().queryKey, USER);
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
});
