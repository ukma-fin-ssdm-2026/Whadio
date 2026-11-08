import {
  infiniteQueryOptions,
  matchQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import type { Schemas } from "@/shared/api/types";
import { unwrap } from "@/shared/api/unwrap";

export type Member = Schemas["MemberRead"];
export type AssignableRole = Schemas["InvitedRole"];

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

export function useChangeMemberRole(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: AssignableRole; self: boolean }) =>
      unwrap(
        apiClient.PATCH("/api/v1/workspaces/{workspace_id}/members/{user_id}", {
          params: { path: { workspace_id: workspaceId, user_id: userId } },
          body: { role },
        }),
      ),
    onSettled: (_data, error, { role, self }) => {
      const demotedSelf = self && role === "member" && !error;
      return queryClient.invalidateQueries({
        queryKey: ["workspaces"],
        // A Moderator who made themselves a Member may no longer read the invitations, whose
        // panel closes once the refreshed workspace says so.
        predicate: (query) =>
          !demotedSelf ||
          !matchQuery({ queryKey: ["workspaces", workspaceId, "invitations"] }, query),
      });
    },
  });
}
