import { List, Paper } from "@mui/material";
import type { ReactNode } from "react";

export function ListPanel({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <Paper variant="outlined" sx={{ overflow: "hidden" }}>
      <List
        aria-label={label}
        disablePadding
        sx={{ "& > li + li": { borderTop: 1, borderColor: "divider" } }}
      >
        {children}
      </List>
    </Paper>
  );
}
