import type { Schemas, TranscriptRead } from "@/shared/api/types";

export const NO_MATCH = "No transcript matches your search.";

export type LabelledSegment = Schemas["SegmentRead"] & {
  speaker: string;
};

export function matchingSegments(
  transcript: TranscriptRead | null,
  query: string,
): LabelledSegment[] {
  const speakers = new Map<string | null, string>(
    (transcript?.speakers ?? []).map((item) => [item.id, item.display_name]),
  );
  const wanted = query.toLowerCase();
  return (transcript?.segments ?? [])
    .map((item) => ({
      ...item,
      speaker: speakers.get(item.speaker_id) ?? "Unknown speaker",
    }))
    .filter(
      (item) =>
        item.text.toLowerCase().includes(wanted) || item.speaker.toLowerCase().includes(wanted),
    );
}
