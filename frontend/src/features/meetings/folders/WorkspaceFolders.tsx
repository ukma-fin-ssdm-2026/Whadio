import CreateNewFolderOutlinedIcon from "@mui/icons-material/CreateNewFolderOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import {
  Alert,
  Button,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Menu,
  MenuItem,
  Stack,
} from "@mui/material";
import { useState } from "react";
import { ApiError } from "@/shared/api/errors";
import type { Schemas } from "@/shared/api/types";
import { countOf } from "@/shared/lib/plural";
import { canManage } from "@/shared/lib/roles";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { SectionHeader } from "@/shared/ui/SectionHeader";
import { useDeleteFolder, useRestoreFolder } from "../api/folders";
import { FolderNameDialog } from "./FolderNameDialog";

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

// A draft without a folder creates one.
interface FolderDraft {
  folder?: Folder;
}

function recoveryMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === "FOLDER_RECOVERY_CONFLICT") {
    return "This folder cannot be restored because its meetings have changed since deletion.";
  }
  if (error instanceof ApiError && error.code === "FOLDER_EXISTS") {
    return "A folder with this name already exists. Rename it, then try again.";
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
  const manageable = canManage(role);
  const notify = useNotify();
  const deleteFolder = useDeleteFolder(workspaceId);
  const restoreFolder = useRestoreFolder(workspaceId);
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);
  const [menuFolder, setMenuFolder] = useState<Folder | null>(null);
  const [draft, setDraft] = useState<FolderDraft | null>(null);
  const [folderToDelete, setFolderToDelete] = useState<Folder | null>(null);

  const closeMenu = () => {
    setMenuAnchor(null);
    setMenuFolder(null);
  };

  // The server keeps a deleted folder's recovery until it is used, so a name clash can be retried.
  const restore = async (folder: Folder) => {
    try {
      await restoreFolder.mutateAsync(folder.id);
      notify("Folder restored.");
    } catch (caught) {
      const retry = caught instanceof ApiError && caught.code === "FOLDER_EXISTS";
      notify(
        recoveryMessage(caught),
        "error",
        retry ? { label: "Try again", onClick: () => restore(folder) } : undefined,
      );
    }
  };

  const removeFolder = async () => {
    if (!folderToDelete) return;
    try {
      await deleteFolder.mutateAsync(folderToDelete.id);
      if (selectedFolderId === folderToDelete.id) onSelect(null);
      setFolderToDelete(null);
      notify("Folder deleted. Its meetings moved to the default folder.", "success", {
        label: "Undo",
        onClick: () => restore(folderToDelete),
      });
    } catch (caught) {
      setFolderToDelete(null);
      notify(
        caught instanceof Error ? caught.message : "The folder could not be deleted.",
        "error",
      );
    }
  };

  const totalMeetings = folders.reduce((total, folder) => total + folder.meeting_count, 0);

  return (
    <Stack sx={{ gap: 1 }}>
      <SectionHeader
        title="Folders"
        actions={
          manageable && (
            <Button
              size="small"
              startIcon={<CreateNewFolderOutlinedIcon />}
              onClick={() => setDraft({})}
            >
              New folder
            </Button>
          )
        }
      />
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
              manageable && (
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
            if (menuFolder) setDraft({ folder: menuFolder });
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

      {draft && (
        <FolderNameDialog
          workspaceId={workspaceId}
          folder={draft.folder}
          onClose={() => setDraft(null)}
        />
      )}

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
    </Stack>
  );
}
