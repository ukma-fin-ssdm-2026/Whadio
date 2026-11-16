import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import type { WorkspaceCreate, WorkspaceUpdate } from "@/shared/api/types";
import { unwrap } from "@/shared/api/unwrap";
import { mapWorkspace } from "../model";

export const workspaceQueries = {
  list: () =>
    queryOptions({
      queryKey: ["workspaces", "list"],
      queryFn: async ({ signal }) => {
        const fetchPage = (cursor?: string) =>
          unwrap(
            apiClient.GET("/api/v1/workspaces", {
              params: { query: { limit: 100, cursor } },
              signal,
            }),
          );
        const result = await fetchPage();
        let cursor = result.pagination.next_cursor;
        while (cursor) {
          const page = await fetchPage(cursor);
          result.items.push(...page.items);
          result.pagination = page.pagination;
          cursor = page.pagination.next_cursor;
        }
        return result;
      },
      select: (page) => page.items.map(mapWorkspace),
    }),
  detail: (workspaceId: string) =>
    queryOptions({
      queryKey: ["workspaces", "detail", workspaceId],
      queryFn: ({ signal }) =>
        unwrap(
          apiClient.GET("/api/v1/workspaces/{workspace_id}", {
            params: { path: { workspace_id: workspaceId } },
            signal,
          }),
        ),
    }),
};

export function useCreateWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (workspace: WorkspaceCreate) =>
      unwrap(apiClient.POST("/api/v1/workspaces", { body: workspace })),
    onSuccess: (workspace) => {
      queryClient.setQueryData(workspaceQueries.detail(workspace.id).queryKey, workspace);
      queryClient.setQueryData(workspaceQueries.list().queryKey, (current) =>
        current ? { ...current, items: [...current.items, workspace] } : current,
      );
    },
  });
}

export function useUpdateWorkspace(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: WorkspaceUpdate) =>
      unwrap(
        apiClient.PATCH("/api/v1/workspaces/{workspace_id}", {
          params: { path: { workspace_id: workspaceId } },
          body: changes,
        }),
      ),
    onSuccess: (workspace) => {
      queryClient.setQueryData(workspaceQueries.detail(workspaceId).queryKey, workspace);
      return queryClient.invalidateQueries({ queryKey: workspaceQueries.list().queryKey });
    },
  });
}
