import { Box, Chip, Divider, List, ListItemButton, Paper, Stack } from "@mui/material";
import { useState } from "react";
import { titleCase } from "@/shared/lib/format";
import { SectionHeader } from "@/shared/ui/SectionHeader";
import { SettingsRow } from "@/shared/ui/SettingsRow";

const SECTIONS = [
  ["workspace", "Workspace"],
  ["assistant", "AI assistant"],
];

export function WorkspaceSettings({ workspace, assistantSettings }) {
  const [section, setSection] = useState("workspace");

  return (
    <Paper variant="outlined" sx={{ display: "flex", flexDirection: { xs: "column", md: "row" } }}>
      <List
        component="nav"
        aria-label="Settings sections"
        sx={{
          flexShrink: 0,
          width: { md: 220 },
          p: 1,
          borderStyle: "solid",
          borderColor: "divider",
          borderWidth: { xs: "0 0 1px", md: "0 1px 0 0" },
        }}
      >
        {SECTIONS.map(([value, label]) => (
          <ListItemButton
            key={value}
            selected={section === value}
            aria-current={section === value ? "true" : undefined}
            onClick={() => setSection(value)}
            sx={{ borderRadius: 1 }}
          >
            {label}
          </ListItemButton>
        ))}
      </List>
      <Box sx={{ flexGrow: 1, minWidth: 0, p: { xs: 2, md: 3 } }}>
        {section === "workspace" ? (
          <>
            <SectionHeader
              title="Workspace settings"
              description={`Configure processing defaults for ${workspace.name}.`}
            />
            <Stack divider={<Divider />} sx={{ mt: 1 }}>
              <SettingsRow
                title="Notes provider"
                description="Whadio gemma-3-12b-it is used for generated notes."
                control={<Chip label={workspace.provider} variant="outlined" />}
              />
              <SettingsRow
                title="Default notes preset"
                description="New uploads use the workspace notes preset."
                control={<Chip label={titleCase(workspace.preset)} variant="outlined" />}
              />
            </Stack>
          </>
        ) : (
          assistantSettings
        )}
      </Box>
    </Paper>
  );
}
