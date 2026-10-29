import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { createTestQueryClient, TestProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { mcpKeyQueries, useCreateMcpKey, useRevokeMcpKey } from "./mcp-keys";

const KEY: Schemas["McpKeyRead"] = {
  id: "0f6c1d2e-8a4b-4c5d-9e0f-1a2b3c4d5e6f",
  created_at: "2026-10-25T10:00:00Z",
  expires_at: null,
  revoked_at: null,
  is_active: true,
};

const CREATED: Schemas["McpKeyCreated"] = {
  ...KEY,
  id: "1a2b3c4d-8a4b-4c5d-9e0f-1a2b3c4d5e6f",
  secret: "whadio_mcp_secret",
};

function renderWithListedKey<T>(hook: () => T) {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(mcpKeyQueries.list().queryKey, {
    items: [KEY],
    pagination: { limit: 100, next_cursor: null, has_more: false },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <TestProviders queryClient={queryClient}>{children}</TestProviders>
  );
  return { ...renderHook(hook, { wrapper }), queryClient };
}

function serveCreate() {
  server.use(http.post("/api/v1/users/me/mcp-keys", ({ response }) => response(201).json(CREATED)));
}

test("list keys live under the accounts domain", () => {
  // Act
  const { queryKey } = mcpKeyQueries.list();

  // Assert
  expect(queryKey).toEqual(["accounts", "mcp-keys"]);
});

test("creating a key returns its secret", async () => {
  // Arrange
  serveCreate();
  const { result } = renderWithListedKey(useCreateMcpKey);

  // Act
  const created = await result.current.mutateAsync(null);

  // Assert
  expect(created.secret).toBe("whadio_mcp_secret");
});

test("creating a key lists it first without its secret", async () => {
  // Arrange
  serveCreate();
  const { result, queryClient } = renderWithListedKey(useCreateMcpKey);

  // Act
  await result.current.mutateAsync(30);

  // Assert
  const { secret: _secret, ...listed } = CREATED;
  expect(queryClient.getQueryData(mcpKeyQueries.list().queryKey)?.items).toEqual([listed, KEY]);
});

test("revoking a key marks the list for a refetch", async () => {
  // Arrange
  server.use(
    http.delete("/api/v1/users/me/mcp-keys/{key_id}", ({ response }) => response(204).empty()),
  );
  const { result, queryClient } = renderWithListedKey(useRevokeMcpKey);

  // Act
  result.current.mutate(KEY.id);

  // Assert
  await waitFor(() =>
    expect(queryClient.getQueryState(mcpKeyQueries.list().queryKey)?.isInvalidated).toBe(true),
  );
});
