import { Box, Stack, Typography } from "@mui/material";
import type { ReactNode } from "react";

interface SettingsRowProps {
  title: string;
  description: string;
  control: ReactNode;
}

export function SettingsRow({ title, description, control }: SettingsRowProps) {
  return (
    <Stack
      direction={{ xs: "column", sm: "row" }}
      sx={{ justifyContent: "space-between", alignItems: { sm: "center" }, gap: 2, py: 2 }}
    >
      <Box>
        <Typography variant="subtitle1" component="h3">
          {title}
        </Typography>
        <Typography variant="body2" color="textSecondary">
          {description}
        </Typography>
      </Box>
      <Stack direction="row" sx={{ gap: 1.5, alignItems: "center", flexShrink: 0 }}>
        {control}
      </Stack>
    </Stack>
  );
}
