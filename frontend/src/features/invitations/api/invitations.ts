import { infiniteQueryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import { ApiError } from "@/shared/api/errors";
import type { Schemas } from "@/shared/api/types";
import { unwrap } from "@/shared/api/unwrap";

export type Invitation = Schemas["InvitationRead"];
export type CreatedInvitation = Schemas["InvitationCreated"];
export type InvitedRole = Schemas["InvitedRole"];

export const invitationQueries = {
  list: (workspaceId: string) =>
    infiniteQueryOptions({
      queryKey: ["workspaces", workspaceId, "invitations"],
      queryFn: ({ pageParam, signal }) =>
        unwrap(
          apiClient.GET("/api/v1/workspaces/{workspace_id}/invitations", {
            params: {
              path: { workspace_id: workspaceId },
              query: { limit: 100, cursor: pageParam || null },
            },
            signal,
          }),
        ),
      initialPageParam: "",
      getNextPageParam: ({ pagination }) => (pagination.has_more ? pagination.next_cursor : null),
      select: ({ pages }) => ({ items: pages.flatMap((page) => page.items) }),
    }),
};

export function useCreateInvitation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["InvitationCreate"]) =>
      unwrap(
        apiClient.POST("/api/v1/workspaces/{workspace_id}/invitations", {
          params: { path: { workspace_id: workspaceId } },
          body,
        }),
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: invitationQueries.list(workspaceId).queryKey }),
    // An invite-only link is shown once; discard it as soon as the dialog releases the mutation.
    gcTime: 0,
  });
}

export function useCancelInvitation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (invitationId: string) =>
      unwrap(
        apiClient.POST("/api/v1/workspaces/{workspace_id}/invitations/{invitation_id}/cancel", {
          params: { path: { workspace_id: workspaceId, invitation_id: invitationId } },
        }),
      ),
    onSettled: (_data, error) => {
      if (!error || (error instanceof ApiError && error.code === "INVITATION_NOT_PENDING")) {
        return queryClient.invalidateQueries({
          queryKey: invitationQueries.list(workspaceId).queryKey,
        });
      }
    },
  });
}

// Link bodies contain secrets, so redemption calls use local component state instead of Query.
export function previewInvitation(id: string, token: string, signal?: AbortSignal) {
  return unwrap(
    apiClient.POST("/api/v1/invitations/{invitation_id}/preview", {
      params: { path: { invitation_id: id } },
      body: { token },
      signal,
    }),
  );
}

export function acceptInvitation(id: string, token: string) {
  return unwrap(
    apiClient.POST("/api/v1/invitations/{invitation_id}/accept", {
      params: { path: { invitation_id: id } },
      body: { token },
    }),
  );
}

export function registerInvitation(id: string, body: Schemas["RegistrationComplete"]) {
  return unwrap(
    apiClient.POST("/api/v1/invitations/{invitation_id}/register", {
      params: { path: { invitation_id: id } },
      body,
    }),
  );
}

export function declineInvitation(id: string, token: string) {
  return unwrap(
    apiClient.POST("/api/v1/invitations/{invitation_id}/decline", {
      params: { path: { invitation_id: id } },
      body: { token },
    }),
  );
}
