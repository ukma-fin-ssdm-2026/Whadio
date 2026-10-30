import { apiClient } from "./shared/api/client";
import type { MeetingRead, NotePage, PlaybackLink, TranscriptRead } from "./shared/api/types";
import { unwrap } from "./shared/api/unwrap";

const PAGE = { limit: 100 };

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

  getRecording(meetingId: string): Promise<PlaybackLink> {
    return unwrap(
      apiClient.GET("/api/v1/meetings/{meeting_id}/recording", {
        params: { path: { meeting_id: meetingId } },
      }),
    );
  },
};
