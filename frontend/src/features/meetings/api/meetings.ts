import {
  infiniteQueryOptions,
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import type { Schemas } from "@/shared/api/types";
import { unwrap } from "@/shared/api/unwrap";
import { isInProgress, mapMeeting } from "../model";

export const MEETINGS_PER_PAGE = 100;
export const POLL_INTERVAL_MS = 10_000;
const FIRST_PAGE = "";

const workspaceListsKey = (workspaceId: string) => ["meetings", "list", workspaceId] as const;

function fetchMeetingPage(workspaceId: string, name: string, cursor: string, signal: AbortSignal) {
  return unwrap(
    apiClient.GET("/api/v1/workspaces/{workspace_id}/meetings", {
      params: {
        path: { workspace_id: workspaceId },
        query: { limit: MEETINGS_PER_PAGE, cursor: cursor || null, name: name || null },
      },
      signal,
    }),
  );
}

export const pollWhileInProgress = (
  items: Pick<Schemas["MeetingSummary"], "processing_state">[],
) => (items.some((item) => isInProgress(item.processing_state)) ? POLL_INTERVAL_MS : false);

export const meetingQueries = {
  list: (workspaceId: string, name = "") =>
    infiniteQueryOptions({
      queryKey: [...workspaceListsKey(workspaceId), "pages", { name }],
      queryFn: ({ pageParam, signal }) => fetchMeetingPage(workspaceId, name, pageParam, signal),
      initialPageParam: FIRST_PAGE,
      getNextPageParam: ({ pagination }) => (pagination.has_more ? pagination.next_cursor : null),
      refetchInterval: ({ state }) =>
        pollWhileInProgress(state.data?.pages.flatMap((page) => page.items) ?? []),
      select: ({ pages }) => pages.flatMap((page) => page.items.map(mapMeeting)),
    }),
  // useQueries has no infinite mode, so the views spanning workspaces read one page of each.
  latest: (workspaceId: string, name = "") =>
    queryOptions({
      queryKey: [...workspaceListsKey(workspaceId), "latest", { name }],
      queryFn: ({ signal }) => fetchMeetingPage(workspaceId, name, FIRST_PAGE, signal),
      refetchInterval: ({ state }) => pollWhileInProgress(state.data?.items ?? []),
    }),
};

interface RecordingUpload {
  file: File;
  name: string;
}

export function useUploadMeeting(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, name }: RecordingUpload) =>
      unwrap(
        apiClient.POST("/api/v1/workspaces/{workspace_id}/meetings", {
          params: { path: { workspace_id: workspaceId } },
          body: { file, name: name.trim() || undefined },
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: workspaceListsKey(workspaceId) });
    },
  });
}
