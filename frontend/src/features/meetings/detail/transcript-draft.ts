import { z } from "zod";
import type { RevisionInput, TranscriptRead } from "@/shared/api/types";

const SPEAKER_NAME_MAX = 200;

// Indexed by position in the base revision: its ids are valid only for that revision.
export const transcriptDraft = z.object({
  speakers: z.array(
    z.object({
      name: z
        .string()
        .trim()
        .min(1, "Enter a name")
        // Code points, as the server counts them; `length` would count UTF-16 units.
        .refine((name) => [...name].length <= SPEAKER_NAME_MAX, {
          message: `Use ${SPEAKER_NAME_MAX} characters or fewer`,
        }),
    }),
  ),
  segments: z.array(z.object({ text: z.string() })),
});

export type TranscriptDraft = z.infer<typeof transcriptDraft>;

export function draftOf(base: TranscriptRead): TranscriptDraft {
  return {
    speakers: base.speakers.map(({ display_name }) => ({ name: display_name })),
    segments: base.segments.map(({ text }) => ({ text })),
  };
}

export function revisionInput(base: TranscriptRead, draft: TranscriptDraft): RevisionInput | null {
  const speakers = base.speakers.flatMap(({ id, display_name }, index) => {
    const renamed = draft.speakers[index]?.name.trim();
    return renamed === undefined || renamed === display_name ? [] : [{ id, display_name: renamed }];
  });
  const segments = base.segments.flatMap(({ id, text }, index) => {
    const corrected = draft.segments[index]?.text;
    return corrected === undefined || corrected === text ? [] : [{ id, text: corrected }];
  });
  if (!speakers.length && !segments.length) return null;
  return {
    base_revision_id: base.revision.id,
    ...(segments.length ? { segments } : {}),
    ...(speakers.length ? { speakers } : {}),
  };
}

export function countChanges(input: RevisionInput | null): number {
  return (input?.segments?.length ?? 0) + (input?.speakers?.length ?? 0);
}
