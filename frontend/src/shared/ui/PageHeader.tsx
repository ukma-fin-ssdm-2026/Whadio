import { Box, Stack, Typography } from "@mui/material";
import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  overline?: string;
  description?: string;
  actions?: ReactNode;
}

export function PageHeader({ title, overline, description, actions }: PageHeaderProps) {
  return (
    <Stack
      direction="row"
      sx={{ justifyContent: "space-between", alignItems: "flex-start", gap: 2 }}
    >
      <Box sx={{ minWidth: 0 }}>
        {overline && (
          <Typography variant="overline" component="p" color="textSecondary">
            {overline}
          </Typography>
        )}
        <Typography variant="h1" sx={{ overflowWrap: "anywhere" }}>
          {title}
        </Typography>
        {description && <Typography color="textSecondary">{description}</Typography>}
      </Box>
      {actions && (
        <Stack direction="row" sx={{ gap: 1, alignItems: "center", flexShrink: 0 }}>
          {actions}
        </Stack>
      )}
    </Stack>
  );
}
