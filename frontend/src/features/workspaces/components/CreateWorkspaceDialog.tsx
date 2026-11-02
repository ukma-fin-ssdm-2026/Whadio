import { zodResolver } from "@hookform/resolvers/zod";
import AddOutlinedIcon from "@mui/icons-material/AddOutlined";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
} from "@mui/material";
import { useState } from "react";
import { type UseFormSetError, useForm } from "react-hook-form";
import { z } from "zod";
import type { ApiError } from "@/shared/api/errors";
import type { Schemas } from "@/shared/api/types";
import { titleCase } from "@/shared/lib/format";
import { FormTextField } from "@/shared/ui/FormTextField";
import { useCreateWorkspace } from "../api/workspaces";

const PRESETS: Schemas["Preset"][] = ["summary", "detailed", "interview"];

const workspaceCreate = z.object({
  name: z.string().trim().min(1, "Enter a workspace name").max(100, "Use 100 characters or fewer"),
  default_preset: z.enum(PRESETS),
});

type WorkspaceCreateValues = z.infer<typeof workspaceCreate>;

function showServerError(error: ApiError, setError: UseFormSetError<WorkspaceCreateValues>) {
  const nameError = error.details.find(({ field }) => field === "name");
  if (nameError || error.status === 422) {
    setError("name", { type: "server", message: nameError?.message ?? error.message });
    return;
  }
  setError("root.server", { type: "server", message: error.message });
}

interface CreateWorkspaceDialogProps {
  onCreated: (workspaceId: string) => void;
}

export function CreateWorkspaceDialog({ onCreated }: CreateWorkspaceDialogProps) {
  const [open, setOpen] = useState(false);
  const create = useCreateWorkspace();
  const { control, handleSubmit, reset, setError, formState } = useForm({
    resolver: zodResolver(workspaceCreate),
    defaultValues: { name: "", default_preset: "summary" as const },
  });

  const close = () => {
    if (create.isPending) return;
    setOpen(false);
    reset();
  };
  const submit = handleSubmit((values) =>
    create.mutate(values, {
      onSuccess: (workspace) => {
        setOpen(false);
        reset();
        onCreated(workspace.id);
      },
      onError: (error) => showServerError(error, setError),
    }),
  );

  return (
    <>
      <Button variant="contained" startIcon={<AddOutlinedIcon />} onClick={() => setOpen(true)}>
        Create workspace
      </Button>
      <Dialog open={open} onClose={close} fullWidth maxWidth="xs">
        <DialogTitle>Create workspace</DialogTitle>
        <DialogContent>
          <Stack
            component="form"
            id="create-workspace-form"
            noValidate
            onSubmit={submit}
            sx={{ gap: 2, pt: 1 }}
          >
            <FormTextField
              control={control}
              name="name"
              label="Workspace name"
              autoComplete="organization"
              autoFocus
              required
            />
            <FormTextField
              control={control}
              name="default_preset"
              label="Default notes preset"
              select
            >
              {PRESETS.map((preset) => (
                <MenuItem key={preset} value={preset}>
                  {titleCase(preset)}
                </MenuItem>
              ))}
            </FormTextField>
            {formState.errors.root?.server?.message && (
              <Alert severity="error">{formState.errors.root.server.message}</Alert>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={close} disabled={create.isPending}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="create-workspace-form"
            variant="contained"
            disabled={create.isPending}
          >
            {create.isPending ? "Creating..." : "Create"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
