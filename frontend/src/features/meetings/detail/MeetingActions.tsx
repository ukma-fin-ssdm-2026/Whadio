import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlineOutlined";
import DriveFileMoveOutlinedIcon from "@mui/icons-material/DriveFileMoveOutlined";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  Menu,
  MenuItem,
  Select,
  TextField,
  Tooltip,
} from "@mui/material";
import { useId, useState } from "react";
import type { Schemas } from "@/shared/api/types";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { useDeleteMeeting, useUpdateMeeting } from "../api/meetings";
import type { Meeting } from "../model";

type Folder = Schemas["FolderRead"];

interface MeetingActionsProps {
  meeting: Meeting;
  role: Schemas["Role"];
  userId: string;
  folders: Folder[];
  onDeleted: () => void;
}

export function MeetingActions({ meeting, role, userId, folders, onDeleted }: MeetingActionsProps) {
  const notify = useNotify();
  const folderLabelId = useId();
  const updateMeeting = useUpdateMeeting(meeting.id, meeting.workspaceId);
  const deleteMeeting = useDeleteMeeting(meeting.id, meeting.workspaceId);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [renameOpen, setRenameOpen] = useState(false);
  const [moveOpen, setMoveOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [name, setName] = useState(meeting.title);
  const [folderId, setFolderId] = useState(meeting.folderId);
  const canDelete = role === "moderator" || role === "owner" || meeting.createdByUserId === userId;

  const closeMenu = () => setAnchor(null);

  const rename = async () => {
    if (!name.trim()) return;
    try {
      await updateMeeting.mutateAsync({ name: name.trim() });
      setRenameOpen(false);
      notify("Meeting renamed.");
    } catch {
      return;
    }
  };

  const move = async () => {
    try {
      await updateMeeting.mutateAsync({ folder_id: folderId });
      setMoveOpen(false);
      notify("Meeting moved.");
    } catch {
      return;
    }
  };

  const remove = async () => {
    try {
      await deleteMeeting.mutateAsync();
      setDeleteOpen(false);
      notify("Meeting deleted.");
      onDeleted();
    } catch (error) {
      notify(error instanceof Error ? error.message : "The meeting could not be deleted.", "error");
    }
  };

  return (
    <>
      <Tooltip title="Meeting actions" arrow>
        <IconButton
          aria-label="Meeting actions"
          onClick={(event) => setAnchor(event.currentTarget)}
        >
          <MoreVertIcon />
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={closeMenu}>
        <MenuItem
          onClick={() => {
            setName(meeting.title);
            setRenameOpen(true);
            closeMenu();
          }}
        >
          <EditOutlinedIcon fontSize="small" sx={{ mr: 1 }} /> Rename
        </MenuItem>
        <MenuItem
          onClick={() => {
            setFolderId(meeting.folderId);
            setMoveOpen(true);
            closeMenu();
          }}
        >
          <DriveFileMoveOutlinedIcon fontSize="small" sx={{ mr: 1 }} /> Move
        </MenuItem>
        {canDelete && (
          <MenuItem
            onClick={() => {
              setDeleteOpen(true);
              closeMenu();
            }}
          >
            <DeleteOutlineIcon fontSize="small" sx={{ mr: 1 }} /> Delete
          </MenuItem>
        )}
      </Menu>

      <Dialog open={renameOpen} onClose={() => setRenameOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Rename meeting</DialogTitle>
        <DialogContent>
          {updateMeeting.error && <Alert severity="error">{updateMeeting.error.message}</Alert>}
          <TextField
            autoFocus
            fullWidth
            label="Meeting name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void rename();
            }}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRenameOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            loading={updateMeeting.isPending}
            disabled={!name.trim()}
            onClick={rename}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={moveOpen} onClose={() => setMoveOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Move meeting</DialogTitle>
        <DialogContent>
          {updateMeeting.error && <Alert severity="error">{updateMeeting.error.message}</Alert>}
          <FormControl fullWidth sx={{ mt: 1 }}>
            <InputLabel id={folderLabelId}>Folder</InputLabel>
            <Select
              labelId={folderLabelId}
              label="Folder"
              value={folderId}
              onChange={(event) => setFolderId(event.target.value)}
            >
              {folders.map((folder) => (
                <MenuItem key={folder.id} value={folder.id}>
                  {folder.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setMoveOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            loading={updateMeeting.isPending}
            disabled={!folderId || folderId === meeting.folderId}
            onClick={move}
          >
            Move
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={deleteOpen}
        title="Delete meeting?"
        confirmLabel="Delete meeting"
        destructive
        pending={deleteMeeting.isPending}
        onConfirm={remove}
        onCancel={() => setDeleteOpen(false)}
      >
        This permanently deletes the recording, transcript and notes. This action cannot be undone.
      </ConfirmDialog>
    </>
  );
}
