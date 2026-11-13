import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlineOutlined";
import DriveFileMoveOutlinedIcon from "@mui/icons-material/DriveFileMoveOutlined";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import ShareOutlinedIcon from "@mui/icons-material/ShareOutlined";
import { IconButton, Menu, MenuItem, Tooltip } from "@mui/material";
import { useState } from "react";
import type { Schemas } from "@/shared/api/types";
import { canManage } from "@/shared/lib/roles";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { useDeleteMeeting } from "../api/meetings";
import type { Meeting } from "../model";
import { AccessDialog, type WorkspaceMembers } from "./AccessDialog";
import { MoveMeetingDialog } from "./MoveMeetingDialog";
import { RenameMeetingDialog } from "./RenameMeetingDialog";
import { ShareDialog } from "./ShareDialog";

type Folder = Schemas["FolderRead"];

interface MeetingActionsProps {
  meeting: Meeting;
  role: Schemas["Role"];
  userId: string;
  folders: Folder[];
  members: WorkspaceMembers;
  onLeave: () => void;
  requestsHref: (shareId: string) => string;
}

type OpenDialog = "rename" | "move" | "share" | "access" | "delete" | null;

export function MeetingActions({
  meeting,
  role,
  userId,
  folders,
  members,
  onLeave,
  requestsHref,
}: MeetingActionsProps) {
  const notify = useNotify();
  const deleteMeeting = useDeleteMeeting(meeting.id, meeting.workspaceId);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [dialog, setDialog] = useState<OpenDialog>(null);
  const canDelete = canManage(role) || meeting.createdByUserId === userId;

  const open = (next: OpenDialog) => {
    setDialog(next);
    setAnchor(null);
  };
  const close = () => setDialog(null);

  const remove = async () => {
    try {
      await deleteMeeting.mutateAsync();
      close();
      notify("Meeting deleted.");
      onLeave();
    } catch (error) {
      close();
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
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
        <MenuItem onClick={() => open("rename")}>
          <EditOutlinedIcon fontSize="small" sx={{ mr: 1 }} /> Rename
        </MenuItem>
        <MenuItem onClick={() => open("move")}>
          <DriveFileMoveOutlinedIcon fontSize="small" sx={{ mr: 1 }} /> Move
        </MenuItem>
        <MenuItem onClick={() => open("share")}>
          <ShareOutlinedIcon fontSize="small" sx={{ mr: 1 }} /> Share
        </MenuItem>
        {canManage(role) && (
          <MenuItem onClick={() => open("access")}>
            <LockOutlinedIcon fontSize="small" sx={{ mr: 1 }} /> Access
          </MenuItem>
        )}
        {canDelete && (
          <MenuItem onClick={() => open("delete")}>
            <DeleteOutlineIcon fontSize="small" sx={{ mr: 1 }} /> Delete
          </MenuItem>
        )}
      </Menu>

      {dialog === "rename" && <RenameMeetingDialog meeting={meeting} onClose={close} />}
      {dialog === "move" && (
        <MoveMeetingDialog meeting={meeting} folders={folders} onClose={close} />
      )}
      {dialog === "share" && (
        <ShareDialog meetingId={meeting.id} requestsHref={requestsHref} onClose={close} />
      )}
      {dialog === "access" && (
        <AccessDialog
          meeting={meeting}
          userId={userId}
          members={members}
          onClose={close}
          onLostAccess={onLeave}
        />
      )}

      <ConfirmDialog
        open={dialog === "delete"}
        title="Delete meeting?"
        confirmLabel="Delete meeting"
        destructive
        pending={deleteMeeting.isPending}
        onConfirm={remove}
        onCancel={close}
      >
        This permanently deletes the recording, transcript and notes. This action cannot be undone.
      </ConfirmDialog>
    </>
  );
}
