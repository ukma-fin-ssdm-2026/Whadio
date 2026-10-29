import { Box, Card, Chip, Stack, Typography } from "@mui/material";
import { useState } from "react";
import { titleCase } from "@/shared/lib/format";

export function WorkspaceSettings({ workspace, assistantSettings }) {
  const [section, setSection] = useState("workspace");

  return (
    <Card className="settings-panel">
      <Box className="settings-nav">
        <Typography variant="overline" className="eyebrow">
          Settings
        </Typography>
        <button
          className={section === "workspace" ? "settings-nav-item active" : "settings-nav-item"}
          type="button"
          onClick={() => setSection("workspace")}
        >
          Workspace
        </button>
        <button
          className={section === "assistant" ? "settings-nav-item active" : "settings-nav-item"}
          type="button"
          onClick={() => setSection("assistant")}
        >
          AI assistant
        </button>
      </Box>

      {section === "workspace" ? (
        <Stack className="settings-options" sx={{ gap: 1.25 }}>
          <Box>
            <Typography variant="h2">Workspace settings</Typography>
            <Typography color="textSecondary">
              Configure processing defaults for {workspace.name}.
            </Typography>
          </Box>

          <Card className="settings-option-card">
            <Stack
              direction={{ xs: "column", md: "row" }}
              sx={{ justifyContent: "space-between", gap: 2 }}
            >
              <Box>
                <Typography variant="subtitle1" component="h3">
                  Notes provider
                </Typography>
                <Typography color="textSecondary">
                  Whadio gemma-3-12b-it is used for generated notes.
                </Typography>
              </Box>
              <Chip label={workspace.provider} variant="outlined" />
            </Stack>
          </Card>

          <Card className="settings-option-card">
            <Stack
              direction={{ xs: "column", md: "row" }}
              sx={{ justifyContent: "space-between", gap: 2 }}
            >
              <Box>
                <Typography variant="subtitle1" component="h3">
                  Default notes preset
                </Typography>
                <Typography color="textSecondary">
                  New uploads use the workspace notes preset.
                </Typography>
              </Box>
              <Chip label={titleCase(workspace.preset)} variant="outlined" />
            </Stack>
          </Card>
        </Stack>
      ) : (
        assistantSettings
      )}
    </Card>
  );
}
