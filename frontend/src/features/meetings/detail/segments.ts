import type { Schemas, TranscriptRead } from "@/shared/api/types";

export const NO_MATCH = "No transcript matches your search.";

const leading = (word: string) => [...word][0]?.toUpperCase() ?? "";

export function speakerInitials(name: string): string {
  const [first = "", ...rest] = name.trim().split(/\s+/);
  const last = rest.at(-1);
  if (last === undefined) return leading(first);
  return leading(first) + (/^\d+$/.test(last) ? last : leading(last));
}

export type LabelledSegment = Schemas["SegmentRead"] & {
  index: number;
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
    .map((item, index) => ({
      ...item,
      index,
      speaker: speakers.get(item.speaker_id) ?? "Unknown speaker",
    }))
    .filter(
      (item) =>
        item.text.toLowerCase().includes(wanted) || item.speaker.toLowerCase().includes(wanted),
    );
}
