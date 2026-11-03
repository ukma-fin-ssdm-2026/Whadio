import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { errorBody, meetingSummary, page } from "@/shared/testing/fixtures";
import { createTestQueryClient, TestProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import {
  folderQueries,
  useCreateFolder,
  useDeleteFolder,
  useRenameFolder,
  useRestoreFolder,
} from "./folders";
import { meetingQueries } from "./meetings";

type Wrapper = ({ children }: { children: ReactNode }) => ReactNode;

const PLANNING: Schemas["FolderRead"] = {
  id: "planning",
  name: "Planning",
  is_default: false,
  meeting_count: 0,
};

function seedCaches() {
  const queryClient = createTestQueryClient();
  for (const workspaceId of ["workspace", "other"]) {
    queryClient.setQueryData(meetingQueries.latest(workspaceId).queryKey, page([meetingSummary()]));
    queryClient.setQueryData(folderQueries.list(workspaceId).queryKey, page([PLANNING]));
  }
  const wrapper: Wrapper = ({ children }) => (
    <TestProviders queryClient={queryClient}>{children}</TestProviders>
  );
  return { queryClient, wrapper };
}

const isInvalidated = (
  queryClient: ReturnType<typeof createTestQueryClient>,
  queryKey: readonly unknown[],
) => queryClient.getQueryState(queryKey)?.isInvalidated;

function serveFolders() {
  server.use(
    http.post("/api/v1/workspaces/{workspace_id}/folders", ({ response }) =>
      response(201).json(PLANNING),
    ),
    http.patch("/api/v1/workspaces/{workspace_id}/folders/{folder_id}", ({ response }) =>
      response(200).json(PLANNING),
    ),
    http.delete("/api/v1/workspaces/{workspace_id}/folders/{folder_id}", ({ response }) =>
      response(204).empty(),
    ),
    http.post("/api/v1/workspaces/{workspace_id}/folders/{folder_id}/restore", ({ response }) =>
      response(200).json(PLANNING),
    ),
  );
}

const changes = {
  create: async (wrapper: Wrapper) => {
    const { result } = renderHook(() => useCreateFolder("workspace"), { wrapper });
    await result.current.mutateAsync("Planning");
  },
  rename: async (wrapper: Wrapper) => {
    const { result } = renderHook(() => useRenameFolder("workspace"), { wrapper });
    await result.current.mutateAsync({ folderId: "planning", name: "Planning" });
  },
  delete: async (wrapper: Wrapper) => {
    const { result } = renderHook(() => useDeleteFolder("workspace"), { wrapper });
    await result.current.mutateAsync("planning");
  },
  restore: async (wrapper: Wrapper) => {
    const { result } = renderHook(() => useRestoreFolder("workspace"), { wrapper });
    await result.current.mutateAsync("planning");
  },
};

test.for(["create", "rename", "delete", "restore"] as const)(
  "a folder %s marks its workspace's folders for a refetch",
  async (change) => {
    // Arrange
    serveFolders();
    const { queryClient, wrapper } = seedCaches();

    // Act
    await changes[change](wrapper);

    // Assert
    expect(isInvalidated(queryClient, folderQueries.list("workspace").queryKey)).toBe(true);
  },
);

test.for(["delete", "restore"] as const)(
  "a folder %s marks its workspace's meetings for a refetch",
  async (change) => {
    // Arrange
    serveFolders();
    const { queryClient, wrapper } = seedCaches();

    // Act
    await changes[change](wrapper);

    // Assert
    expect(isInvalidated(queryClient, meetingQueries.latest("workspace").queryKey)).toBe(true);
  },
);

test.for(["delete", "restore"] as const)(
  "a folder %s leaves other workspaces alone",
  async (change) => {
    // Arrange
    serveFolders();
    const { queryClient, wrapper } = seedCaches();

    // Act
    await changes[change](wrapper);

    // Assert
    expect(isInvalidated(queryClient, meetingQueries.latest("other").queryKey)).toBe(false);
  },
);

test("a failed folder deletion refreshes nothing", async () => {
  // Arrange
  server.use(
    http.delete("/api/v1/workspaces/{workspace_id}/folders/{folder_id}", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "Not found")),
    ),
  );
  const { queryClient, wrapper } = seedCaches();

  // Act
  await expect(changes.delete(wrapper)).rejects.toThrow();

  // Assert
  expect(isInvalidated(queryClient, meetingQueries.latest("workspace").queryKey)).toBe(false);
});
