import {
  Alert,
  Button,
  Chip,
  CircularProgress,
  Divider,
  MenuItem,
  Paper,
  Stack,
  TextField,
} from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { Schemas } from "@/shared/api/types";
import { titleCase } from "@/shared/lib/format";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { SectionHeader } from "@/shared/ui/SectionHeader";
import { SettingsRow } from "@/shared/ui/SettingsRow";
import { useDeleteWorkspace, useUpdateWorkspace, workspaceQueries } from "../api/workspaces";
import { PRESETS } from "../model";

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

function notesDescription({ notes_provider, notes_model }: Schemas["WorkspaceRead"]) {
  const provider = titleCase(notes_provider);
  const written = `${provider} ${notes_model} is used for generated notes.`;
  return notes_provider === "whadio"
    ? written
    : `${written} Transcripts in the context set are sent to ${provider}.`;
}

interface WorkspaceDefaultsProps {
  workspaceId: string;
  onDeleted: () => void;
}

function WorkspaceDefaults({ workspaceId, onDeleted }: WorkspaceDefaultsProps) {
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
          description={notesDescription(workspace)}
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
        {workspace.is_personal ? (
          <Alert severity="info">A personal workspace cannot be deleted.</Alert>
        ) : (
          workspace.my_role === "owner" && (
            <DeleteWorkspace workspace={workspace} onDeleted={onDeleted} />
          )
        )}
      </Stack>
    </>
  );
}

function DeleteWorkspace({
  workspace,
  onDeleted,
}: {
  workspace: Schemas["WorkspaceRead"];
  onDeleted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const remove = useDeleteWorkspace(workspace.id);
  const notify = useNotify();
  const confirm = () => {
    remove.mutate(undefined, {
      onSuccess: onDeleted,
      onError: (caught) => notify(caught.message, "error"),
    });
  };

  return (
    <>
      <SettingsRow
        title="Delete workspace"
        description="Permanently delete this workspace and everything in it."
        control={
          <Button color="error" variant="outlined" onClick={() => setConfirming(true)}>
            Delete workspace
          </Button>
        }
      />
      <ConfirmDialog
        open={confirming}
        title={`Delete ${workspace.name}?`}
        confirmLabel="Delete workspace"
        destructive
        pending={remove.isPending}
        onConfirm={confirm}
        onCancel={() => setConfirming(false)}
      >
        {workspace.name} and all of its folders, meetings, recordings, transcripts and notes will be
        permanently deleted.
      </ConfirmDialog>
    </>
  );
}

export function WorkspaceSettings({
  workspaceId,
  onDeleted,
}: {
  workspaceId: string;
  onDeleted: () => void;
}) {
  return (
    <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 } }}>
      <WorkspaceDefaults workspaceId={workspaceId} onDeleted={onDeleted} />
    </Paper>
  );
}
