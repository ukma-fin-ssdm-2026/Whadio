import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import type { Schemas } from "@/shared/api/types";
import { expectNoContent, unwrap } from "@/shared/api/unwrap";

export type McpKey = Schemas["McpKeyRead"];

export const mcpKeyQueries = {
  list: () =>
    queryOptions({
      queryKey: ["accounts", "mcp-keys"],
      queryFn: ({ signal }) =>
        unwrap(
          apiClient.GET("/api/v1/users/me/mcp-keys", { params: { query: { limit: 100 } }, signal }),
        ),
    }),
};

export function useCreateMcpKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (expiresInDays: number | null) => {
      const { secret, ...key } = await unwrap(
        apiClient.POST("/api/v1/users/me/mcp-keys", { body: { expires_in_days: expiresInDays } }),
      );
      return { key, secret };
    },
    onSuccess: ({ key }) =>
      queryClient.setQueryData(
        mcpKeyQueries.list().queryKey,
        (page) => page && { ...page, items: [key, ...page.items] },
      ),
    // The secret is shown once; drop the finished mutation as soon as nothing observes it.
    gcTime: 0,
  });
}

export function useRevokeMcpKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) =>
      expectNoContent(
        apiClient.DELETE("/api/v1/users/me/mcp-keys/{key_id}", {
          params: { path: { key_id: keyId } },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: mcpKeyQueries.list().queryKey }),
  });
}
