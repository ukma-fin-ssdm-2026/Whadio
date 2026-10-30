import { API_ORIGIN } from "@/shared/api/client";
import type { operations } from "@/shared/api/schema.gen";

type TranscriptExportOptions = NonNullable<
  operations["export_transcript_api_v1_meetings__meeting_id__transcript_export_get"]["parameters"]["query"]
>;

const meetingUrl = (meetingId: string) =>
  `${API_ORIGIN}/api/v1/meetings/${encodeURIComponent(meetingId)}`;

export function transcriptExportUrl(
  meetingId: string,
  { format = "markdown", version = "current", timestamps = true }: TranscriptExportOptions = {},
): string {
  const query = new URLSearchParams({ format, version });
  if (format === "markdown") query.set("timestamps", String(timestamps));
  return `${meetingUrl(meetingId)}/transcript/export?${query}`;
}

export function notesExportUrl(meetingId: string): string {
  return `${meetingUrl(meetingId)}/notes/export`;
}
