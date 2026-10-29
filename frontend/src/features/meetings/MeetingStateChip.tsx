import { Chip, CircularProgress } from "@mui/material";
import type { Schemas } from "@/shared/api/types";
import { IN_PROGRESS_LABELS } from "./model";

export function MeetingStateChip({ state }: { state: Schemas["ProcessingState"] }) {
  if (state === "processed") return null;
  if (state === "failed") return <Chip size="small" color="error" label="Failed" />;
  return (
    <Chip
      size="small"
      variant="outlined"
      icon={<CircularProgress size={12} thickness={5} color="inherit" />}
      label={IN_PROGRESS_LABELS[state]}
    />
  );
}
