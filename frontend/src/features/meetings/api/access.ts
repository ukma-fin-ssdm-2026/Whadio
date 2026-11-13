import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import type { Schemas } from "@/shared/api/types";
import { unwrap } from "@/shared/api/unwrap";
import { detailKey, workspaceListsKey } from "./keys";

export type MeetingAccess = Schemas["AccessRead"];

export const accessQueries = {
  detail: (meetingId: string) =>
    queryOptions({
      queryKey: [...detailKey(meetingId), "access"],
      queryFn: ({ signal }) =>
        unwrap(
          apiClient.GET("/api/v1/meetings/{meeting_id}/access", {
            params: { path: { meeting_id: meetingId } },
            signal,
          }),
        ),
    }),
};

export function useSetMeetingAccess(meetingId: string, workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (access: Schemas["AccessInput"]) =>
      unwrap(
        apiClient.PUT("/api/v1/meetings/{meeting_id}/access", {
          params: { path: { meeting_id: meetingId } },
          body: access,
        }),
      ),
    onSuccess: async (access) => {
      queryClient.setQueryData(accessQueries.detail(meetingId).queryKey, access);
      await queryClient.invalidateQueries({ queryKey: workspaceListsKey(workspaceId) });
    },
  });
}
