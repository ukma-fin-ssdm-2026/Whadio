import { formatDuration } from "@/shared/lib/format-duration";

export function mapMeeting(item) {
  return {
    id: item.id,
    workspaceId: item.workspace_id,
    title: item.name,
    date: item.recorded_at,
    state: item.processing_state,
    duration: formatDuration(item.duration_seconds),
    source: item.source_type === "extension" ? "Google Meet" : "Upload",
    recordingAvailable: item.recording_available ?? false,
    failureReason: item.failure_reason,
  };
}

export const IN_PROGRESS_LABELS = {
  recording: "Recording",
  queued: "Queued",
  processing: "Processing",
};

export function isProcessing(meeting) {
  return Object.hasOwn(IN_PROGRESS_LABELS, meeting.state);
}

export function matchesStateFilter(meeting, stateFilter) {
  return stateFilter === "all" || meeting.state === stateFilter;
}
