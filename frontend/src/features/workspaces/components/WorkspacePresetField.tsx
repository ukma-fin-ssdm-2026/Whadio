import { Alert, CircularProgress, FormControl, InputLabel, MenuItem, Select } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { titleCase } from "@/shared/lib/format";
import { workspaceQueries } from "../api/workspaces";

export function WorkspacePresetField({ workspaceId }: { workspaceId: string }) {
  const { data: workspace, error } = useQuery(workspaceQueries.detail(workspaceId));
  if (!workspace) {
    return error ? (
      <Alert severity="warning">
        The note preset could not be shown ({error.message}). Uploads still use the workspace
        default.
      </Alert>
    ) : (
      <CircularProgress aria-label="Loading note preset" size={24} />
    );
  }
  const preset = workspace.default_preset;
  return (
    <FormControl fullWidth>
      <InputLabel>Note preset</InputLabel>
      <Select label="Note preset" value={preset} disabled>
        <MenuItem value={preset}>{titleCase(preset)} (workspace default)</MenuItem>
      </Select>
    </FormControl>
  );
}
