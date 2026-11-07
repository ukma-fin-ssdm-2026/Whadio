import { zodResolver } from "@hookform/resolvers/zod";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle } from "@mui/material";
import { type UseFormSetError, useForm } from "react-hook-form";
import { z } from "zod";
import type { ApiError } from "@/shared/api/errors";
import type { Schemas } from "@/shared/api/types";
import { FormTextField } from "@/shared/ui/FormTextField";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { useCreateFolder, useRenameFolder } from "../api/folders";

const folderName = z.object({
  name: z.string().trim().min(1, "Enter a folder name").max(100, "Use 100 characters or fewer"),
});

type FolderNameValues = z.infer<typeof folderName>;

function showServerError(error: ApiError, setError: UseFormSetError<FolderNameValues>) {
  if (error.code === "FOLDER_EXISTS") {
    setError("name", { type: "server", message: "A folder with this name already exists" });
    return;
  }
  const nameError = error.details.find(({ field }) => field === "name");
  if (nameError) {
    setError("name", { type: "server", message: nameError.message });
    return;
  }
  setError("root.server", { type: "server", message: error.message });
}

interface FolderNameDialogProps {
  workspaceId: string;
  folder?: Schemas["FolderRead"];
  onClose: () => void;
}

export function FolderNameDialog({ workspaceId, folder, onClose }: FolderNameDialogProps) {
  const notify = useNotify();
  const createFolder = useCreateFolder(workspaceId);
  const renameFolder = useRenameFolder(workspaceId);
  const pending = createFolder.isPending || renameFolder.isPending;
  const { control, handleSubmit, setError, formState } = useForm({
    resolver: zodResolver(folderName),
    defaultValues: { name: folder?.name ?? "" },
  });

  const close = () => {
    if (!pending) onClose();
  };
  const handlers = (done: string) => ({
    onSuccess: () => {
      notify(done);
      onClose();
    },
    onError: (error: ApiError) => showServerError(error, setError),
  });
  const submit = handleSubmit(({ name }) => {
    if (pending) return;
    if (folder) renameFolder.mutate({ folderId: folder.id, name }, handlers("Folder renamed."));
    else createFolder.mutate(name, handlers("Folder created."));
  });

  return (
    <Dialog open onClose={close} maxWidth="xs" fullWidth>
      <DialogTitle>{folder ? "Rename folder" : "Create folder"}</DialogTitle>
      <DialogContent>
        <form id="folder-name-form" noValidate onSubmit={submit}>
          <FormTextField
            control={control}
            name="name"
            label="Folder name"
            autoComplete="off"
            autoFocus
            fullWidth
            sx={{ mt: 1 }}
          />
        </form>
        {formState.errors.root?.server?.message && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {formState.errors.root.server.message}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={close} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" form="folder-name-form" variant="contained" loading={pending}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}
