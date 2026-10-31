import {
  infiniteQueryOptions,
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import { ApiError } from "@/shared/api/errors";
import type { Schemas } from "@/shared/api/types";
import { unwrap } from "@/shared/api/unwrap";
import { isInProgress, type Meeting, mapMeeting } from "../model";

export const MEETINGS_PER_PAGE = 100;
export const POLL_INTERVAL_MS = 10_000;
export const TRANSCRIPT_PENDING = "pending" as const;
const FIRST_PAGE = "";
const CURRENT_NOTE_ONLY = { limit: 1 };

// The server signs a playback link for 5 minutes (meetings/recordings.py).
const RECORDING_LINK_LIFE_MS = 5 * 60_000;
const RECORDING_LINK_FRESH_MS = 4 * 60_000;

const workspaceListsKey = (workspaceId: string) => ["meetings", "list", workspaceId] as const;
const detailKey = (meetingId: string) => ["meetings", "detail", meetingId] as const;

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

async function fetchTranscript(
  meetingId: string,
  meetingState: Meeting["state"],
  revisionId: string | null,
  signal: AbortSignal,
) {
  try {
    return await unwrap(
      apiClient.GET("/api/v1/meetings/{meeting_id}/transcript", {
        params: { path: { meeting_id: meetingId }, query: { revision_id: revisionId } },
        signal,
      }),
    );
  } catch (error) {
    // None yet while processing, none at all after a failure; a named revision has to exist.
    if (error instanceof ApiError && error.code === "NOT_TRANSCRIBED" && !revisionId) {
      return meetingState === "processing" ? TRANSCRIPT_PENDING : null;
    }
    throw error;
  }
}

const pollWhileInProgress = (items: Pick<Schemas["MeetingSummary"], "processing_state">[]) =>
  items.some((item) => isInProgress(item.processing_state)) ? POLL_INTERVAL_MS : false;

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
  detail: (meetingId: string) =>
    queryOptions({
      queryKey: detailKey(meetingId),
      queryFn: ({ signal }) =>
        unwrap(
          apiClient.GET("/api/v1/meetings/{meeting_id}", {
            params: { path: { meeting_id: meetingId } },
            signal,
          }),
        ),
      refetchInterval: ({ state }) => pollWhileInProgress(state.data ? [state.data] : []),
      select: mapMeeting,
    }),
  transcript: (
    { id, state: meetingState }: Pick<Meeting, "id" | "state">,
    revisionId: string | null,
  ) =>
    queryOptions({
      queryKey: [...detailKey(id), "transcript", { revisionId }],
      queryFn: ({ signal }) => fetchTranscript(id, meetingState, revisionId, signal),
      // Not `processed`, unlike the notes: it is saved before them and outlives their failure.
      enabled: meetingState !== "recording" && meetingState !== "queued",
      refetchInterval: ({ state }) =>
        state.data === TRANSCRIPT_PENDING ? POLL_INTERVAL_MS : false,
    }),
  notes: ({ id, state }: Pick<Meeting, "id" | "state">) =>
    queryOptions({
      queryKey: [...detailKey(id), "notes"],
      queryFn: ({ signal }) =>
        unwrap(
          apiClient.GET("/api/v1/meetings/{meeting_id}/notes", {
            params: { path: { meeting_id: id }, query: CURRENT_NOTE_ONLY },
            signal,
          }),
        ),
      select: ({ items }) => items[0] ?? null,
      enabled: state === "processed",
    }),
  recording: ({ id, recordingAvailable }: Pick<Meeting, "id" | "recordingAvailable">) =>
    queryOptions({
      queryKey: [...detailKey(id), "recording"],
      queryFn: ({ signal }) =>
        unwrap(
          apiClient.GET("/api/v1/meetings/{meeting_id}/recording", {
            params: { path: { meeting_id: id } },
            signal,
          }),
        ),
      enabled: recordingAvailable,
      staleTime: RECORDING_LINK_FRESH_MS,
      gcTime: RECORDING_LINK_LIFE_MS,
      // A new link changes the player's source, which restarts playback.
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
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
