import { Paper, Typography } from "@mui/material";
import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  hint?: string;
  action?: ReactNode;
}

export function EmptyState({ title, hint, action }: EmptyStateProps) {
  return (
    <Paper variant="outlined" sx={{ p: 4, textAlign: "center", borderStyle: "dashed" }}>
      <Typography variant="subtitle1">{title}</Typography>
      {hint && <Typography color="textSecondary">{hint}</Typography>}
      {action}
    </Paper>
  );
}
