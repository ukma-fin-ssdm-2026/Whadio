import {
  Alert,
  Chip,
  CircularProgress,
  Divider,
  MenuItem,
  Paper,
  Stack,
  TextField,
} from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import type { Schemas } from "@/shared/api/types";
import { titleCase } from "@/shared/lib/format";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { SectionHeader } from "@/shared/ui/SectionHeader";
import { SettingsRow } from "@/shared/ui/SettingsRow";
import { useUpdateWorkspace, workspaceQueries } from "../api/workspaces";

const PRESETS: Schemas["Preset"][] = ["summary", "detailed", "interview"];

function PresetSelect({ workspace }: { workspace: Schemas["WorkspaceRead"] }) {
  const update = useUpdateWorkspace(workspace.id);
  const notify = useNotify();

  const choose = (value: string) => {
    const preset = PRESETS.find((item) => item === value);
    if (!preset) return;
    update.mutate(
      { default_preset: preset },
      { onError: (caught) => notify(caught.message, "error") },
    );
  };

  return (
    <TextField
      select
      size="small"
      value={workspace.default_preset}
      disabled={update.isPending}
      onChange={(event) => choose(event.target.value)}
      slotProps={{ htmlInput: { "aria-label": "Default notes preset" } }}
      sx={{ minWidth: 140 }}
    >
      {PRESETS.map((preset) => (
        <MenuItem key={preset} value={preset}>
          {titleCase(preset)}
        </MenuItem>
      ))}
    </TextField>
  );
}

function WorkspaceDefaults({ workspaceId }: { workspaceId: string }) {
  const { data: workspace, error } = useQuery(workspaceQueries.detail(workspaceId));
  if (!workspace) {
    return error ? (
      <Alert severity="error">{error.message}</Alert>
    ) : (
      <CircularProgress aria-label="Loading workspace settings" />
    );
  }
  return (
    <>
      <SectionHeader
        title="Workspace settings"
        description={`Configure processing defaults for ${workspace.name}.`}
      />
      <Stack divider={<Divider />} sx={{ mt: 1 }}>
        <SettingsRow
          title="Notes provider"
          description="Whadio gemma-3-12b-it is used for generated notes."
          control={<Chip label={titleCase(workspace.notes_provider)} variant="outlined" />}
        />
        <SettingsRow
          title="Default notes preset"
          description="New uploads use the workspace notes preset."
          control={
            workspace.my_role === "owner" ? (
              <PresetSelect workspace={workspace} />
            ) : (
              <Chip label={titleCase(workspace.default_preset)} variant="outlined" />
            )
          }
        />
      </Stack>
    </>
  );
}

export function WorkspaceSettings({ workspaceId }: { workspaceId: string }) {
  return (
    <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 } }}>
      <WorkspaceDefaults workspaceId={workspaceId} />
    </Paper>
  );
}
