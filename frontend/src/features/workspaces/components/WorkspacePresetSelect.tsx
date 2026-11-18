import {
  Alert,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
} from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useId } from "react";
import type { Preset } from "@/shared/api/types";
import { titleCase } from "@/shared/lib/format";
import { workspaceQueries } from "../api/workspaces";
import { PRESETS } from "../model";

interface WorkspacePresetSelectProps {
  workspaceId: string;
  value: Preset | null;
  onChange: (preset: Preset) => void;
}

export function WorkspacePresetSelect({
  workspaceId,
  value,
  onChange,
}: WorkspacePresetSelectProps) {
  const labelId = useId();
  const { data: workspace, error } = useQuery(workspaceQueries.detail(workspaceId));
  if (!workspace && !error) {
    return <CircularProgress aria-label="Loading note preset" size={24} />;
  }
  const workspaceDefault = workspace?.default_preset ?? null;
  return (
    <Stack sx={{ gap: 1.5 }}>
      {!workspace && error && (
        <Alert severity="warning">
          The note preset could not be shown ({error.message}). Without a choice the workspace
          default is used.
        </Alert>
      )}
      <FormControl fullWidth>
        <InputLabel id={labelId}>Note preset</InputLabel>
        <Select
          labelId={labelId}
          label="Note preset"
          value={value ?? workspaceDefault ?? ""}
          onChange={(event) => {
            const preset = PRESETS.find((item) => item === event.target.value);
            if (preset) onChange(preset);
          }}
        >
          {PRESETS.map((preset) => (
            <MenuItem key={preset} value={preset}>
              {titleCase(preset)}
              {preset === workspaceDefault && " (workspace default)"}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Stack>
  );
}
