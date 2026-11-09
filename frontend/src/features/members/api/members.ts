import { infiniteQueryOptions } from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import type { Schemas } from "@/shared/api/types";
import { unwrap } from "@/shared/api/unwrap";

export type Member = Schemas["MemberRead"];

export const memberQueries = {
  list: (workspaceId: string) =>
    infiniteQueryOptions({
      queryKey: ["workspaces", workspaceId, "members"],
      queryFn: ({ pageParam, signal }) =>
        unwrap(
          apiClient.GET("/api/v1/workspaces/{workspace_id}/members", {
            params: {
              path: { workspace_id: workspaceId },
              query: { limit: 100, cursor: pageParam || null },
            },
            signal,
          }),
        ),
      initialPageParam: "",
      getNextPageParam: ({ pagination }) => pagination.next_cursor,
      select: ({ pages }) => pages.flatMap((page) => page.items),
    }),
};
