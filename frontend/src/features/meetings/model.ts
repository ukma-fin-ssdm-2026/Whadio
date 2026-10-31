import type { MeetingPage, Schemas } from "@/shared/api/types";
import { formatDuration } from "@/shared/lib/format-duration";
import { countOf } from "@/shared/lib/plural";

type ProcessingState = Schemas["ProcessingState"];
type InProgressState = Exclude<ProcessingState, "processed" | "failed">;

export type StateFilter = "all" | ProcessingState;
export type MeetingTab = "notes" | "transcript" | "recording";

export interface Meeting {
  id: string;
  workspaceId: string;
  title: string;
  date: string;
  state: ProcessingState;
  duration: string;
  source: "Google Meet" | "Upload";
  recordingAvailable: boolean;
  failureReason: string | null;
}

type MeetingFields = Schemas["MeetingSummary"] &
  Partial<Pick<Schemas["MeetingRead"], "recording_available" | "failure_reason">>;

export function mapMeeting(item: MeetingFields): Meeting {
  return {
    id: item.id,
    workspaceId: item.workspace_id,
    title: item.name,
    date: item.recorded_at,
    state: item.processing_state,
    duration: formatDuration(item.duration_seconds),
    source: item.source_type === "extension" ? "Google Meet" : "Upload",
    recordingAvailable: item.recording_available ?? false,
    failureReason: item.failure_reason ?? null,
  };
}

const FAILURE_TEXT = new Map([
  ["transcription_failed", "This recording could not be transcribed."],
  ["notes_failed", "Notes could not be written for this meeting."],
  ["provider_unavailable", "The notes provider was unavailable, so no notes were written."],
  ["provider_rejected", "The notes provider refused the request, so no notes were written."],
  ["processing_timeout", "Processing took too long and was stopped."],
]);

export function describeFailure(reason: string | null): string {
  return FAILURE_TEXT.get(reason ?? "") ?? "Processing failed for this meeting.";
}

export const IN_PROGRESS_LABELS: Record<InProgressState, string> = {
  recording: "Recording",
  queued: "Queued",
  processing: "Processing",
};

export function isInProgress(state: ProcessingState): state is InProgressState {
  return Object.hasOwn(IN_PROGRESS_LABELS, state);
}

export function isProcessing(meeting: Pick<Meeting, "state">): boolean {
  return isInProgress(meeting.state);
}

export function matchesStateFilter(meeting: Pick<Meeting, "state">, filter: StateFilter): boolean {
  return filter === "all" || meeting.state === filter;
}

export function describeMeetingFigures({ items, pagination }: MeetingPage): string {
  const active = items.filter((item) => isInProgress(item.processing_state)).length;
  return pagination.has_more
    ? `${items.length}+ meetings, ${active} active in the latest ${items.length}`
    : `${countOf(items.length, "meeting")}, ${active} active`;
}
