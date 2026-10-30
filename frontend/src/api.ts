import { API_ORIGIN, apiClient } from "./shared/api/client";
import type { operations } from "./shared/api/schema.gen";
import type { MeetingRead, NotePage, PlaybackLink, TranscriptRead } from "./shared/api/types";
import { unwrap } from "./shared/api/unwrap";

type TranscriptExportOptions = NonNullable<
  operations["export_transcript_api_v1_meetings__meeting_id__transcript_export_get"]["parameters"]["query"]
>;

const PAGE = { limit: 100 };

const meetingUrl = (meetingId: string) =>
  `${API_ORIGIN}/api/v1/meetings/${encodeURIComponent(meetingId)}`;

export const api = {
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
};
