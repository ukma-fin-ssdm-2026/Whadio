import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
} from "@mui/material";
import { useId, useState } from "react";
import type { Schemas } from "@/shared/api/types";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { useUpdateMeeting } from "../api/meetings";
import type { Meeting } from "../model";

interface MoveMeetingDialogProps {
  meeting: Meeting;
  folders: Schemas["FolderRead"][];
  onClose: () => void;
}

export function MoveMeetingDialog({ meeting, folders, onClose }: MoveMeetingDialogProps) {
  const notify = useNotify();
  const folderLabelId = useId();
  const updateMeeting = useUpdateMeeting(meeting.id, meeting.workspaceId);
  const [folderId, setFolderId] = useState(meeting.folderId);

  const close = () => {
    if (!updateMeeting.isPending) onClose();
  };
  const move = () =>
    updateMeeting.mutate(
      { folder_id: folderId },
      {
        onSuccess: () => {
          notify("Meeting moved.");
          onClose();
        },
      },
    );

  return (
    <Dialog open onClose={close} maxWidth="xs" fullWidth>
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
        <Button onClick={close} disabled={updateMeeting.isPending}>
          Cancel
        </Button>
        <Button
          variant="contained"
          loading={updateMeeting.isPending}
          disabled={folderId === meeting.folderId}
          onClick={move}
        >
          Move
        </Button>
      </DialogActions>
    </Dialog>
  );
}
