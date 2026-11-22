import {
  infiniteQueryOptions,
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { apiClient } from "@/shared/api/client";
import { ApiError } from "@/shared/api/errors";
import type {
  MeetingUpdate,
  NotesRegeneration,
  Preset,
  RevisionInput,
  Schemas,
} from "@/shared/api/types";
import { expectNoContent, unwrap } from "@/shared/api/unwrap";
import type { RecordedRange } from "../dateRange";
import { isInProgress, type Meeting, mapMeeting } from "../model";
import { detailKey, foldersKey, workspaceListsKey } from "./keys";

export const MEETINGS_PER_PAGE = 100;
export const POLL_INTERVAL_MS = 10_000;
export const TRANSCRIPT_PENDING = "pending" as const;
const FIRST_PAGE = "";
const CURRENT_NOTE_ONLY = { limit: 1 };
const NOTE_VERSIONS_PER_PAGE = 20;

// The server signs a playback link for 5 minutes (meetings/recordings.py).
const RECORDING_LINK_LIFE_MS = 5 * 60_000;
const RECORDING_LINK_FRESH_MS = 4 * 60_000;

const transcriptsKey = (meetingId: string) => [...detailKey(meetingId), "transcript"] as const;
const notesKey = (meetingId: string) => [...detailKey(meetingId), "notes"] as const;

// Notes too: a regeneration keeps the previous ones current while `processing` and once `failed`.
const hasTranscriptStage = (state: Meeting["state"]) =>
  state === "processing" || state === "processed" || state === "failed";

function fetchMeetingPage(
  workspaceId: string,
  name: string,
  folderId: string | null,
  range: RecordedRange,
  cursor: string,
  signal: AbortSignal,
) {
  return unwrap(
    apiClient.GET("/api/v1/workspaces/{workspace_id}/meetings", {
      params: {
        path: { workspace_id: workspaceId },
        query: {
          limit: MEETINGS_PER_PAGE,
          cursor: cursor || null,
          folder_id: folderId,
          name: name || null,
          recorded_from: range.recordedFrom ?? null,
          recorded_to: range.recordedTo ?? null,
        },
      },
      signal,
    }),
  );
}

function fetchNotes(
  meetingId: string,
  query: { limit: number; cursor?: string | null },
  signal: AbortSignal,
) {
  return unwrap(
    apiClient.GET("/api/v1/meetings/{meeting_id}/notes", {
      params: { path: { meeting_id: meetingId }, query },
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

// Unlike a transient failure, this means the cached copy must not stay on screen.
export const isMeetingGone = (error: ApiError | null) =>
  error?.status === 403 || error?.status === 404;

const pollWhileInProgress = (items: Pick<Schemas["MeetingSummary"], "processing_state">[]) =>
  items.some((item) => isInProgress(item.processing_state)) ? POLL_INTERVAL_MS : false;

export const meetingQueries = {
  list: (
    workspaceId: string,
    name = "",
    folderId: string | null = null,
    range: RecordedRange = {},
  ) =>
    infiniteQueryOptions({
      queryKey: [...workspaceListsKey(workspaceId), "pages", { name, folderId, ...range }],
      queryFn: ({ pageParam, signal }) =>
        fetchMeetingPage(workspaceId, name, folderId, range, pageParam, signal),
      initialPageParam: FIRST_PAGE,
      getNextPageParam: ({ pagination }) => (pagination.has_more ? pagination.next_cursor : null),
      refetchInterval: ({ state }) =>
        pollWhileInProgress(state.data?.pages.flatMap((page) => page.items) ?? []),
      select: ({ pages }) => pages.flatMap((page) => page.items.map(mapMeeting)),
    }),
  // useQueries has no infinite mode, so the views spanning workspaces read one page of each.
  latest: (workspaceId: string, name = "", range: RecordedRange = {}) =>
    queryOptions({
      queryKey: [...workspaceListsKey(workspaceId), "latest", { name, ...range }],
      queryFn: ({ signal }) => fetchMeetingPage(workspaceId, name, null, range, FIRST_PAGE, signal),
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
      refetchInterval: ({ state }) =>
        isMeetingGone(state.error) ? false : pollWhileInProgress(state.data ? [state.data] : []),
      select: mapMeeting,
    }),
  transcript: (
    { id, state: meetingState }: Pick<Meeting, "id" | "state">,
    revisionId: string | null,
  ) =>
    queryOptions({
      queryKey: [...transcriptsKey(id), { revisionId }],
      queryFn: ({ signal }) => fetchTranscript(id, meetingState, revisionId, signal),
      enabled: hasTranscriptStage(meetingState),
      refetchInterval: ({ state }) =>
        state.data === TRANSCRIPT_PENDING ? POLL_INTERVAL_MS : false,
    }),
  notes: ({ id, state }: Pick<Meeting, "id" | "state">) =>
    queryOptions({
      queryKey: notesKey(id),
      queryFn: ({ signal }) => fetchNotes(id, CURRENT_NOTE_ONLY, signal),
      select: ({ items, pagination }) => ({
        current: items[0] ?? null,
        hasEarlier: pagination.has_more,
      }),
      enabled: hasTranscriptStage(state),
    }),
  noteVersions: (meetingId: string) =>
    infiniteQueryOptions({
      queryKey: [...notesKey(meetingId), "versions"],
      queryFn: ({ pageParam, signal }) =>
        fetchNotes(meetingId, { limit: NOTE_VERSIONS_PER_PAGE, cursor: pageParam || null }, signal),
      initialPageParam: FIRST_PAGE,
      getNextPageParam: ({ pagination }) => (pagination.has_more ? pagination.next_cursor : null),
      select: ({ pages }) => pages.flatMap((page) => page.items),
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

export function useForgetRecordingLink({
  id,
  recordingAvailable,
}: Pick<Meeting, "id" | "recordingAvailable">) {
  const queryClient = useQueryClient();
  // `enabled: false` keeps cached data, and `gcTime` doesn't run while the player stays mounted.
  useEffect(() => {
    if (recordingAvailable) return;
    const { queryKey } = meetingQueries.recording({ id, recordingAvailable });
    queryClient.removeQueries({ queryKey });
  }, [queryClient, id, recordingAvailable]);
}

export function useRefreshNotesWhenSettled({ id, state }: Pick<Meeting, "id" | "state">) {
  const queryClient = useQueryClient();
  const settled = !isInProgress(state);
  const seen = useRef({ id, settled });
  useEffect(() => {
    const before = seen.current;
    seen.current = { id, settled };
    if (before.id === id && !before.settled && settled) {
      void queryClient.invalidateQueries({ queryKey: notesKey(id) });
    }
  }, [queryClient, id, settled]);
}

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

export function useEditTranscript(meeting: Pick<Meeting, "id" | "state">) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (edit: RevisionInput) =>
      unwrap(
        apiClient.POST("/api/v1/meetings/{meeting_id}/transcript/revisions", {
          params: { path: { meeting_id: meeting.id } },
          body: edit,
        }),
      ),
    onSuccess: (revision) => {
      // Every cached revision's `is_current` changed with it.
      queryClient.invalidateQueries({ queryKey: transcriptsKey(meeting.id), refetchType: "none" });
      queryClient.setQueryData(meetingQueries.transcript(meeting, null).queryKey, revision);
      // Exact: refetching the recording link under it would restart playback.
      return queryClient.invalidateQueries({ queryKey: detailKey(meeting.id), exact: true });
    },
    onError: (error) => {
      if (error.code !== "STALE_REVISION") return;
      return queryClient.invalidateQueries({ queryKey: transcriptsKey(meeting.id) });
    },
  });
}

export function useRegenerateNotes({ id, workspaceId }: Pick<Meeting, "id" | "workspaceId">) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (preset: Preset | null) => {
      const body: NotesRegeneration = preset === null ? {} : { preset };
      return unwrap(
        apiClient.POST("/api/v1/meetings/{meeting_id}/notes", {
          params: { path: { meeting_id: id } },
          body,
        }),
      );
    },
    onSuccess: () => {
      // The 202 means `processing`: polling starts now, and the settle hook sees a run that
      // ends before the next poll.
      queryClient.setQueryData(
        meetingQueries.detail(id).queryKey,
        (meeting): Schemas["MeetingRead"] | undefined =>
          meeting && { ...meeting, processing_state: "processing", failure_reason: null },
      );
      return queryClient.invalidateQueries({ queryKey: workspaceListsKey(workspaceId) });
    },
    onError: (error) => {
      if (error.code !== "NOTES_IN_PROGRESS" && error.code !== "NOT_TRANSCRIBED") return;
      // Exact: refetching the recording link under it would restart playback.
      return queryClient.invalidateQueries({ queryKey: detailKey(id), exact: true });
    },
  });
}

export function useUpdateMeeting(meetingId: string, workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: MeetingUpdate) =>
      unwrap(
        apiClient.PATCH("/api/v1/meetings/{meeting_id}", {
          params: { path: { meeting_id: meetingId } },
          body: changes,
        }),
      ),
    onSuccess: async (meeting) => {
      queryClient.setQueryData(meetingQueries.detail(meetingId).queryKey, meeting);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: workspaceListsKey(workspaceId) }),
        queryClient.invalidateQueries({ queryKey: foldersKey(workspaceId) }),
      ]);
    },
  });
}

export function useDeleteMeeting(meetingId: string, workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      expectNoContent(
        apiClient.DELETE("/api/v1/meetings/{meeting_id}", {
          params: { path: { meeting_id: meetingId } },
        }),
      ),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: detailKey(meetingId) });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: workspaceListsKey(workspaceId) }),
        queryClient.invalidateQueries({ queryKey: foldersKey(workspaceId) }),
      ]);
    },
  });
}
