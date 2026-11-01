import { Box } from "@mui/material";
import type { ReactNode } from "react";

export function ErrorBanner({ children }: { children: ReactNode }) {
  return (
    <Box
      role="alert"
      sx={{
        p: "0.8rem 1rem",
        border: "1px solid rgb(var(--mui-palette-error-mainChannel) / 40%)",
        borderRadius: "0.5rem",
        bgcolor: "rgb(var(--mui-palette-error-mainChannel) / 6%)",
        color: "error.main",
      }}
    >
      {children}
    </Box>
  );
}
