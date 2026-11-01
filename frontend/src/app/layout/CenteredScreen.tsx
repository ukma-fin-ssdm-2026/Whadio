import { CircularProgress, Stack } from "@mui/material";
import type { ReactNode } from "react";

export function CenteredScreen({ children }: { children: ReactNode }) {
  return (
    <Stack
      sx={{
        minHeight: "100vh",
        boxSizing: "border-box",
        p: 2,
        gap: 2,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {children}
    </Stack>
  );
}

export function LoadingScreen() {
  return (
    <CenteredScreen>
      <CircularProgress aria-label="Loading" />
    </CenteredScreen>
  );
}
