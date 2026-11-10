import {
  infiniteQueryOptions,
  matchQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import type { Schemas } from "@/shared/api/types";
import { expectNoContent, unwrap } from "@/shared/api/unwrap";

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

export function useRemoveMember(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId }: { userId: string; leaving: boolean }) =>
      expectNoContent(
        apiClient.DELETE("/api/v1/workspaces/{workspace_id}/members/{user_id}", {
          params: { path: { workspace_id: workspaceId, user_id: userId } },
        }),
      ),
    onSettled: (_data, error, { leaving }) =>
      queryClient.invalidateQueries({
        queryKey: ["workspaces"],
        // The pages of a workspace just left stay open until the caller moves away, and
        // refetching what they show would only be refused.
        refetchType: leaving && !error ? "none" : "active",
      }),
  });
}
