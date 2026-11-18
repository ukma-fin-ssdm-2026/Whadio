import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Stack,
} from "@mui/material";
import { type ReactNode, useState } from "react";
import type { Preset } from "@/shared/api/types";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { useRegenerateNotes } from "../api/meetings";
import type { Meeting } from "../model";

export type PresetFieldProps = { value: Preset | null; onChange: (preset: Preset) => void };

interface RegenerateNotesDialogProps {
  meeting: Pick<Meeting, "id" | "workspaceId">;
  renderPresetField: (field: PresetFieldProps) => ReactNode;
  onClose: () => void;
}

export function RegenerateNotesDialog({
  meeting,
  renderPresetField,
  onClose,
}: RegenerateNotesDialogProps) {
  const notify = useNotify();
  const regenerate = useRegenerateNotes(meeting);
  const [preset, setPreset] = useState<Preset | null>(null);

  const close = () => {
    if (!regenerate.isPending) onClose();
  };
  const submit = () =>
    regenerate.mutate(preset, {
      onSuccess: () => {
        notify("Regenerating the notes.");
        onClose();
      },
    });

  return (
    <Dialog open onClose={close} maxWidth="xs" fullWidth>
      <DialogTitle>Regenerate notes</DialogTitle>
      <DialogContent>
        <Stack sx={{ gap: 2, pt: 1 }}>
          <DialogContentText>
            New notes are written from the current transcript. The earlier notes stay readable.
          </DialogContentText>
          {renderPresetField({ value: preset, onChange: setPreset })}
          {regenerate.error && <Alert severity="error">{regenerate.error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={close} disabled={regenerate.isPending}>
          Cancel
        </Button>
        <Button variant="contained" loading={regenerate.isPending} onClick={submit}>
          Regenerate
        </Button>
      </DialogActions>
    </Dialog>
  );
}
