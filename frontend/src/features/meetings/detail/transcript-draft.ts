import type { RevisionInput, TranscriptRead } from "@/shared/api/types";

// Indexed by position in the base revision: its ids are valid only for that revision.
export interface TranscriptDraft {
  segments: { text: string }[];
}

export function draftOf(base: TranscriptRead): TranscriptDraft {
  return { segments: base.segments.map(({ text }) => ({ text })) };
}

export function revisionInput(base: TranscriptRead, draft: TranscriptDraft): RevisionInput | null {
  const segments = base.segments.flatMap(({ id, text }, index) => {
    const corrected = draft.segments[index]?.text;
    return corrected === undefined || corrected === text ? [] : [{ id, text: corrected }];
  });
  return segments.length ? { base_revision_id: base.revision.id, segments } : null;
}

export function countChanges(input: RevisionInput | null): number {
  return (input?.segments?.length ?? 0) + (input?.speakers?.length ?? 0);
}
