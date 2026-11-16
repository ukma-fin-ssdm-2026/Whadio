import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, test } from "vitest";
import { page, workspaceRead, workspaceSummary } from "@/shared/testing/fixtures";
import { createTestQueryClient, TestProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import {
  useCreateWorkspace,
  useDeleteWorkspace,
  useUpdateWorkspace,
  workspaceQueries,
} from "./workspaces";

const CREATED = workspaceRead({ id: "created", name: "Created Workspace" });
const UPDATED = workspaceRead({ default_preset: "interview" });

function renderUpdate() {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(workspaceQueries.list().queryKey, page([workspaceSummary()]));
  queryClient.setQueryData(workspaceQueries.detail("workspace").queryKey, workspaceRead());
  const wrapper = ({ children }: { children: ReactNode }) => (
    <TestProviders queryClient={queryClient}>{children}</TestProviders>
  );
  const { result } = renderHook(() => useUpdateWorkspace("workspace"), { wrapper });
  return { result, queryClient };
}

function serveUpdate() {
  const bodies: unknown[] = [];
  server.use(
    http.patch("/api/v1/workspaces/{workspace_id}", async ({ request, response }) => {
      bodies.push(await request.json());
      return response(200).json(UPDATED);
    }),
  );
  return bodies;
}

function renderDelete() {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(
    workspaceQueries.list().queryKey,
    page([workspaceSummary(), workspaceSummary({ id: "other", name: "Other" })]),
  );
  queryClient.setQueryData(workspaceQueries.detail("workspace").queryKey, workspaceRead());
  server.use(
    http.delete("/api/v1/workspaces/{workspace_id}", ({ response }) => response(204).empty()),
  );
  const wrapper = ({ children }: { children: ReactNode }) => (
    <TestProviders queryClient={queryClient}>{children}</TestProviders>
  );
  const { result } = renderHook(() => useDeleteWorkspace("workspace"), { wrapper });
  return { result, queryClient };
}

test("workspace keys share the workspaces domain", () => {
  // Act
  const keys = [workspaceQueries.list().queryKey, workspaceQueries.detail("alpha").queryKey];

  // Assert
  expect(keys).toEqual([
    ["workspaces", "list"],
    ["workspaces", "detail", "alpha"],
  ]);
});

test("creating a workspace adds the server copy to the list immediately", async () => {
  // Arrange
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(workspaceQueries.list().queryKey, page([workspaceSummary()]));
  server.use(http.post("/api/v1/workspaces", ({ response }) => response(201).json(CREATED)));
  const wrapper = ({ children }: { children: ReactNode }) => (
    <TestProviders queryClient={queryClient}>{children}</TestProviders>
  );
  const { result } = renderHook(() => useCreateWorkspace(), { wrapper });

  // Act
  await result.current.mutateAsync({ name: "Created Workspace", default_preset: "summary" });

  // Assert
  expect(queryClient.getQueryData(workspaceQueries.list().queryKey)).toEqual(
    page([workspaceSummary(), CREATED]),
  );
});

test("updating a workspace sends only the changes", async () => {
  // Arrange
  const bodies = serveUpdate();
  const { result } = renderUpdate();

  // Act
  await result.current.mutateAsync({ default_preset: "interview" });

  // Assert
  expect(bodies).toEqual([{ default_preset: "interview" }]);
});

test("updating a workspace stores the server's copy of it", async () => {
  // Arrange
  serveUpdate();
  const { result, queryClient } = renderUpdate();

  // Act
  await result.current.mutateAsync({ default_preset: "interview" });

  // Assert
  expect(queryClient.getQueryData(workspaceQueries.detail("workspace").queryKey)).toEqual(UPDATED);
});

test("updating a workspace marks the list for a refetch", async () => {
  // Arrange
  serveUpdate();
  const { result, queryClient } = renderUpdate();

  // Act
  result.current.mutate({ name: "Renamed" });

  // Assert
  await waitFor(() =>
    expect(queryClient.getQueryState(workspaceQueries.list().queryKey)?.isInvalidated).toBe(true),
  );
});

test("deleting a workspace removes it from the cached list", async () => {
  // Arrange
  const { result, queryClient } = renderDelete();

  // Act
  await result.current.mutateAsync();

  // Assert
  expect(queryClient.getQueryData(workspaceQueries.list().queryKey)).toEqual(
    page([workspaceSummary({ id: "other", name: "Other" })]),
  );
});

test("deleting a workspace removes its cached detail", async () => {
  // Arrange
  const { result, queryClient } = renderDelete();

  // Act
  await result.current.mutateAsync();

  // Assert
  expect(queryClient.getQueryData(workspaceQueries.detail("workspace").queryKey)).toBeUndefined();
});
