import { Box, Stack, Typography } from "@mui/material";
import type { ReactNode } from "react";

interface SectionHeaderProps {
  title: string;
  description?: string;
  actions?: ReactNode;
}

export function SectionHeader({ title, description, actions }: SectionHeaderProps) {
  return (
    <Stack
      direction={{ xs: "column", md: "row" }}
      sx={{ justifyContent: "space-between", alignItems: { md: "center" }, gap: 1.5 }}
    >
      <Box>
        <Typography variant="h2">{title}</Typography>
        {description && <Typography color="textSecondary">{description}</Typography>}
      </Box>
      {actions && (
        <Stack direction="row" sx={{ gap: 1 }}>
          {actions}
        </Stack>
      )}
    </Stack>
  );
}
