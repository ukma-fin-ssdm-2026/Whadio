import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import type { Schemas } from "@/shared/api/types";
import { expectNoContent, unwrap } from "@/shared/api/unwrap";
import { detailKey } from "./keys";

export type Share = Schemas["ShareRead"];

const sharesKey = (meetingId: string) => [...detailKey(meetingId), "shares"] as const;

export const shareQueries = {
  list: (meetingId: string) =>
    queryOptions({
      queryKey: sharesKey(meetingId),
      queryFn: ({ signal }) =>
        unwrap(
          apiClient.GET("/api/v1/meetings/{meeting_id}/shares", {
            params: { path: { meeting_id: meetingId }, query: { limit: 100 } },
            signal,
          }),
        ),
      select: (page) => page.items,
    }),
};

export function useCreateShare(meetingId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (share: Schemas["ShareInput"]) =>
      unwrap(
        apiClient.POST("/api/v1/meetings/{meeting_id}/shares", {
          params: { path: { meeting_id: meetingId } },
          body: share,
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sharesKey(meetingId) }),
  });
}

export function useRevokeShare(meetingId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (shareId: string) =>
      expectNoContent(
        apiClient.DELETE("/api/v1/shares/{share_id}", {
          params: { path: { share_id: shareId } },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sharesKey(meetingId) }),
  });
}
