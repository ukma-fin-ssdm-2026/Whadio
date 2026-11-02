import CreateNewFolderOutlinedIcon from "@mui/icons-material/CreateNewFolderOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Menu,
  MenuItem,
  Snackbar,
  Stack,
  TextField,
} from "@mui/material";
import { useState } from "react";
import { ApiError } from "@/shared/api/errors";
import type { Schemas } from "@/shared/api/types";
import { countOf } from "@/shared/lib/plural";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { useCreateFolder, useDeleteFolder, useRenameFolder, useRestoreFolder } from "./api/folders";

type Folder = Schemas["FolderRead"];
type Role = Schemas["Role"];

interface WorkspaceFoldersProps {
  workspaceId: string;
  role: Role;
  folders: Folder[];
  selectedFolderId: string | null;
  loading: boolean;
  error?: string;
  onSelect: (folderId: string | null) => void;
}

interface FolderDraft {
  id: string | null;
  name: string;
}

function recoveryMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === "FOLDER_RECOVERY_CONFLICT") {
    return "This folder cannot be restored because its meetings have changed since deletion.";
  }
  if (error instanceof ApiError && error.code === "FOLDER_EXISTS") {
    return "A folder with this name already exists. Rename it before restoring this folder.";
  }
  return error instanceof Error ? error.message : "The folder could not be restored.";
}

export function WorkspaceFolders({
  workspaceId,
  role,
  folders,
  selectedFolderId,
  loading,
  error,
  onSelect,
}: WorkspaceFoldersProps) {
  const canManage = role === "moderator" || role === "owner";
  const notify = useNotify();
  const createFolder = useCreateFolder(workspaceId);
  const renameFolder = useRenameFolder(workspaceId);
  const deleteFolder = useDeleteFolder(workspaceId);
  const restoreFolder = useRestoreFolder(workspaceId);
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);
  const [menuFolder, setMenuFolder] = useState<Folder | null>(null);
  const [draft, setDraft] = useState<FolderDraft | null>(null);
  const [folderToDelete, setFolderToDelete] = useState<Folder | null>(null);
  const [deletedFolder, setDeletedFolder] = useState<Folder | null>(null);

  const closeMenu = () => {
    setMenuAnchor(null);
    setMenuFolder(null);
  };

  const saveFolder = async () => {
    if (!draft?.name.trim()) return;
    try {
      if (draft.id) {
        await renameFolder.mutateAsync({ folderId: draft.id, name: draft.name.trim() });
        notify("Folder renamed.");
      } else {
        await createFolder.mutateAsync(draft.name.trim());
        notify("Folder created.");
      }
      setDraft(null);
    } catch {
      return;
    }
  };

  const removeFolder = async () => {
    if (!folderToDelete) return;
    try {
      await deleteFolder.mutateAsync(folderToDelete.id);
      setDeletedFolder(folderToDelete);
      if (selectedFolderId === folderToDelete.id) onSelect(null);
      setFolderToDelete(null);
    } catch (error) {
      notify(error instanceof Error ? error.message : "The folder could not be deleted.", "error");
    }
  };

  const restore = async () => {
    if (!deletedFolder) return;
    try {
      await restoreFolder.mutateAsync(deletedFolder.id);
      setDeletedFolder(null);
      notify("Folder restored.");
    } catch (error) {
      setDeletedFolder(null);
      notify(recoveryMessage(error), "error");
    }
  };

  const mutationError = createFolder.error ?? renameFolder.error;
  const totalMeetings = folders.reduce((total, folder) => total + folder.meeting_count, 0);

  return (
    <Stack sx={{ gap: 1 }}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center" }}>
        <strong>Folders</strong>
        {canManage && (
          <Button
            size="small"
            startIcon={<CreateNewFolderOutlinedIcon />}
            onClick={() => setDraft({ id: null, name: "" })}
          >
            New folder
          </Button>
        )}
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
      <List
        aria-label="Workspace folders"
        disablePadding
        sx={{ display: "grid", gridTemplateColumns: { sm: "repeat(2, minmax(0, 1fr))" }, gap: 1 }}
      >
        <ListItem disablePadding>
          <ListItemButton selected={selectedFolderId === null} onClick={() => onSelect(null)}>
            <ListItemText primary="All meetings" secondary={countOf(totalMeetings, "meeting")} />
          </ListItemButton>
        </ListItem>
        {folders.map((folder) => (
          <ListItem
            key={folder.id}
            disablePadding
            secondaryAction={
              canManage && (
                <IconButton
                  aria-label={`Manage ${folder.name}`}
                  onClick={(event) => {
                    setMenuAnchor(event.currentTarget);
                    setMenuFolder(folder);
                  }}
                >
                  <MoreVertIcon />
                </IconButton>
              )
            }
          >
            <ListItemButton
              selected={selectedFolderId === folder.id}
              onClick={() => onSelect(folder.id)}
            >
              <ListItemText
                primary={folder.name}
                secondary={`${countOf(folder.meeting_count, "meeting")}${folder.is_default ? " · Default" : ""}`}
              />
            </ListItemButton>
          </ListItem>
        ))}
      </List>
      {loading && <span>Loading folders…</span>}

      <Menu anchorEl={menuAnchor} open={Boolean(menuAnchor)} onClose={closeMenu}>
        <MenuItem
          onClick={() => {
            if (menuFolder) setDraft({ id: menuFolder.id, name: menuFolder.name });
            closeMenu();
          }}
        >
          Rename
        </MenuItem>
        {!menuFolder?.is_default && (
          <MenuItem
            onClick={() => {
              setFolderToDelete(menuFolder);
              closeMenu();
            }}
          >
            Delete
          </MenuItem>
        )}
      </Menu>

      <Dialog open={draft !== null} onClose={() => setDraft(null)} maxWidth="xs" fullWidth>
        <DialogTitle>{draft?.id ? "Rename folder" : "Create folder"}</DialogTitle>
        <DialogContent>
          {mutationError && <Alert severity="error">{mutationError.message}</Alert>}
          <TextField
            autoFocus
            fullWidth
            label="Folder name"
            value={draft?.name ?? ""}
            onChange={(event) =>
              setDraft((current) => (current ? { ...current, name: event.target.value } : current))
            }
            onKeyDown={(event) => {
              if (event.key === "Enter") void saveFolder();
            }}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDraft(null)}>Cancel</Button>
          <Button
            variant="contained"
            loading={createFolder.isPending || renameFolder.isPending}
            disabled={!draft?.name.trim()}
            onClick={saveFolder}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={folderToDelete !== null}
        title="Delete folder?"
        confirmLabel="Delete folder"
        destructive
        pending={deleteFolder.isPending}
        onConfirm={removeFolder}
        onCancel={() => setFolderToDelete(null)}
      >
        Meetings in this folder will move to the default folder. You can undo this immediately
        afterwards.
      </ConfirmDialog>

      <Snackbar
        open={deletedFolder !== null}
        autoHideDuration={8000}
        onClose={() => setDeletedFolder(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
        message="Folder deleted. Its meetings moved to the default folder."
        action={
          <Button color="inherit" loading={restoreFolder.isPending} onClick={restore}>
            Undo
          </Button>
        }
      />
    </Stack>
  );
}
