import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import { expectNoContent, unwrap } from "@/shared/api/unwrap";
import { foldersKey, workspaceListsKey } from "./keys";

export const folderQueries = {
  list: (workspaceId: string) =>
    queryOptions({
      queryKey: foldersKey(workspaceId),
      queryFn: ({ signal }) =>
        unwrap(
          apiClient.GET("/api/v1/workspaces/{workspace_id}/folders", {
            params: { path: { workspace_id: workspaceId }, query: { limit: 100 } },
            signal,
          }),
        ),
      select: (page) => page.items,
    }),
};

function useRefreshFolders(workspaceId: string) {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: foldersKey(workspaceId) });
}

export function useCreateFolder(workspaceId: string) {
  const refresh = useRefreshFolders(workspaceId);
  return useMutation({
    mutationFn: (name: string) =>
      unwrap(
        apiClient.POST("/api/v1/workspaces/{workspace_id}/folders", {
          params: { path: { workspace_id: workspaceId } },
          body: { name },
        }),
      ),
    onSuccess: refresh,
  });
}

export function useRenameFolder(workspaceId: string) {
  const refresh = useRefreshFolders(workspaceId);
  return useMutation({
    mutationFn: ({ folderId, name }: { folderId: string; name: string }) =>
      unwrap(
        apiClient.PATCH("/api/v1/workspaces/{workspace_id}/folders/{folder_id}", {
          params: { path: { workspace_id: workspaceId, folder_id: folderId } },
          body: { name },
        }),
      ),
    onSuccess: refresh,
  });
}

export function useDeleteFolder(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (folderId: string) =>
      expectNoContent(
        apiClient.DELETE("/api/v1/workspaces/{workspace_id}/folders/{folder_id}", {
          params: { path: { workspace_id: workspaceId, folder_id: folderId } },
        }),
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: foldersKey(workspaceId) }),
        queryClient.invalidateQueries({ queryKey: workspaceListsKey(workspaceId) }),
      ]);
    },
  });
}

export function useRestoreFolder(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (folderId: string) =>
      unwrap(
        apiClient.POST("/api/v1/workspaces/{workspace_id}/folders/{folder_id}/restore", {
          params: { path: { workspace_id: workspaceId, folder_id: folderId } },
        }),
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: foldersKey(workspaceId) }),
        queryClient.invalidateQueries({ queryKey: workspaceListsKey(workspaceId) }),
      ]);
    },
  });
}
