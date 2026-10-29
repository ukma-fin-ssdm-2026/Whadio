import { API_ORIGIN, apiClient } from "./shared/api/client";
import type { operations } from "./shared/api/schema.gen";
import type {
  MeetingPage,
  MeetingRead,
  NotePage,
  PlaybackLink,
  Schemas,
  TranscriptRead,
  WorkspacePage,
  WorkspaceRead,
  WorkspaceUpdate,
} from "./shared/api/types";
import { unwrap } from "./shared/api/unwrap";

export { ApiError } from "./shared/api/errors";

type UploadBody = Schemas["Body_upload_recording_api_v1_workspaces__workspace_id__meetings_post"];

type TranscriptExportOptions = NonNullable<
  operations["export_transcript_api_v1_meetings__meeting_id__transcript_export_get"]["parameters"]["query"]
>;

type RecordingUpload = { file: Blob; name: string };

export function recordingForm({ file, name }: UploadBody): FormData {
  const form = new FormData();
  form.append("file", file);
  const trimmedName = name?.trim();
  if (trimmedName) form.append("name", trimmedName);
  return form;
}

const PAGE = { limit: 100 };

const meetingUrl = (meetingId: string) =>
  `${API_ORIGIN}/api/v1/meetings/${encodeURIComponent(meetingId)}`;

export const api = {
  listWorkspaces(): Promise<WorkspacePage> {
    return unwrap(apiClient.GET("/api/v1/workspaces", { params: { query: PAGE } }));
  },

  getWorkspace(workspaceId: string): Promise<WorkspaceRead> {
    return unwrap(
      apiClient.GET("/api/v1/workspaces/{workspace_id}", {
        params: { path: { workspace_id: workspaceId } },
      }),
    );
  },

  updateWorkspace(workspaceId: string, changes: WorkspaceUpdate): Promise<WorkspaceRead> {
    return unwrap(
      apiClient.PATCH("/api/v1/workspaces/{workspace_id}", {
        params: { path: { workspace_id: workspaceId } },
        body: changes,
      }),
    );
  },

  listMeetings(workspaceId: string): Promise<MeetingPage> {
    return unwrap(
      apiClient.GET("/api/v1/workspaces/{workspace_id}/meetings", {
        params: { path: { workspace_id: workspaceId }, query: PAGE },
      }),
    );
  },

  getMeeting(meetingId: string): Promise<MeetingRead> {
    return unwrap(
      apiClient.GET("/api/v1/meetings/{meeting_id}", {
        params: { path: { meeting_id: meetingId } },
      }),
    );
  },

  getTranscript(meetingId: string, revisionId: string | null = null): Promise<TranscriptRead> {
    return unwrap(
      apiClient.GET("/api/v1/meetings/{meeting_id}/transcript", {
        params: { path: { meeting_id: meetingId }, query: { revision_id: revisionId || null } },
      }),
    );
  },

  listNotes(meetingId: string): Promise<NotePage> {
    return unwrap(
      apiClient.GET("/api/v1/meetings/{meeting_id}/notes", {
        params: { path: { meeting_id: meetingId }, query: PAGE },
      }),
    );
  },

  transcriptExportUrl(
    meetingId: string,
    { format = "markdown", version = "current", timestamps = true }: TranscriptExportOptions = {},
  ): string {
    const query = new URLSearchParams({ format, version });
    if (format === "markdown") query.set("timestamps", String(timestamps));
    return `${meetingUrl(meetingId)}/transcript/export?${query}`;
  },

  notesExportUrl(meetingId: string): string {
    return `${meetingUrl(meetingId)}/notes/export`;
  },

  getRecording(meetingId: string): Promise<PlaybackLink> {
    return unwrap(
      apiClient.GET("/api/v1/meetings/{meeting_id}/recording", {
        params: { path: { meeting_id: meetingId } },
      }),
    );
  },

  uploadMeeting(workspaceId: string, { file, name }: RecordingUpload): Promise<MeetingRead> {
    return unwrap(
      apiClient.POST("/api/v1/workspaces/{workspace_id}/meetings", {
        params: { path: { workspace_id: workspaceId } },
        body: { file, name },
        bodySerializer: recordingForm,
      }),
    );
  },
};
