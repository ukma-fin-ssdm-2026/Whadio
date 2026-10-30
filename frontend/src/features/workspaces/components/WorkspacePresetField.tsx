import { FormControl, InputLabel, MenuItem, Select } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { titleCase } from "@/shared/lib/format";
import { workspaceQueries } from "../api/workspaces";

export function WorkspacePresetField({ workspaceId }: { workspaceId: string }) {
  const { data: workspace } = useQuery(workspaceQueries.detail(workspaceId));
  const preset = workspace?.default_preset ?? "";
  return (
    <FormControl fullWidth>
      <InputLabel>Note preset</InputLabel>
      <Select label="Note preset" value={preset} disabled>
        {preset && <MenuItem value={preset}>{titleCase(preset)} (workspace default)</MenuItem>}
      </Select>
    </FormControl>
  );
}
