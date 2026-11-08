import { Box, Stack, Typography } from "@mui/material";
import type { ReactNode } from "react";
import { formatTimestamp } from "@/shared/lib/format";

interface SegmentRowProps {
  speaker: string;
  startSeconds: number;
  marker?: ReactNode;
  children: ReactNode;
}

export function SegmentRow({ speaker, startSeconds, marker, children }: SegmentRowProps) {
  return (
    <Box
      sx={{
        display: "grid",
        gap: "0.55rem",
        pb: "1rem",
        borderBottom: 1,
        borderBottomColor: "divider",
      }}
    >
      <Stack direction="row" sx={{ gap: 1, alignItems: "center" }}>
        <Box
          sx={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            flex: "0 0 auto",
            width: "1.8rem",
            height: "1.8rem",
            borderRadius: "50%",
            bgcolor: "tint.main",
            color: "tint.contrastText",
            font: "caption",
            lineHeight: 1,
          }}
        >
          {speaker.slice(-2)}
        </Box>
        <Typography variant="subtitle1">{speaker}</Typography>
        <Typography color="primary">{formatTimestamp(startSeconds)}</Typography>
        {marker}
      </Stack>
      {children}
    </Box>
  );
}
