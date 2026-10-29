import { List, Paper } from "@mui/material";
import type { ReactNode } from "react";

export function ListPanel({ children }: { children: ReactNode }) {
  return (
    <Paper variant="outlined" sx={{ overflow: "hidden" }}>
      <List disablePadding sx={{ "& > li + li": { borderTop: 1, borderColor: "divider" } }}>
        {children}
      </List>
    </Paper>
  );
}
