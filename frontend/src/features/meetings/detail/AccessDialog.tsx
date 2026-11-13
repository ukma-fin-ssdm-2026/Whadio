import {
  Alert,
  Button,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  FormHelperText,
  List,
  ListItem,
  ListItemText,
  Radio,
  RadioGroup,
} from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { Schemas } from "@/shared/api/types";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { accessQueries, type MeetingAccess, useSetMeetingAccess } from "../api/access";
import type { Meeting } from "../model";

export interface WorkspaceMembers {
  data: Schemas["MemberRead"][] | undefined;
  error: Error | null;
}

interface AccessDialogProps {
  meeting: Meeting;
  userId: string;
  members: WorkspaceMembers;
  onClose: () => void;
  onLostAccess: () => void;
}

export function AccessDialog({
  meeting,
  userId,
  members,
  onClose,
  onLostAccess,
}: AccessDialogProps) {
  const access = useQuery(accessQueries.detail(meeting.id));
  const loadError = access.error ?? members.error;

  return (
    <Dialog open onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Who can see this meeting</DialogTitle>
      {access.data && members.data ? (
        <AccessForm
          meeting={meeting}
          userId={userId}
          initial={access.data}
          memberList={members.data}
          onClose={onClose}
          onLostAccess={onLostAccess}
        />
      ) : (
        <DialogContent>
          {loadError ? (
            <Alert severity="error">{loadError.message}</Alert>
          ) : (
            <CircularProgress aria-label="Loading access" size={24} />
          )}
        </DialogContent>
      )}
    </Dialog>
  );
}

interface AccessFormProps extends Omit<AccessDialogProps, "members"> {
  initial: MeetingAccess;
  memberList: Schemas["MemberRead"][];
}

function AccessForm({
  meeting,
  userId,
  initial,
  memberList,
  onClose,
  onLostAccess,
}: AccessFormProps) {
  const notify = useNotify();
  const setAccess = useSetMeetingAccess(meeting.id, meeting.workspaceId);
  const [mode, setMode] = useState(initial.access_mode);
  const [selected, setSelected] = useState(
    () => new Set(initial.access_mode === "restricted" ? initial.member_ids : [userId]),
  );
  const restricted = mode === "restricted";
  const leavesSelfOut = restricted && !selected.has(userId);

  const close = () => {
    if (!setAccess.isPending) onClose();
  };
  const toggle = (memberId: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(memberId)) next.add(memberId);
      return next;
    });
  const save = () =>
    setAccess.mutate(
      { access_mode: mode, member_ids: restricted ? [...selected] : [] },
      {
        onSuccess: () => {
          notify("Access updated.");
          if (leavesSelfOut) onLostAccess();
          else onClose();
        },
      },
    );

  return (
    <>
      <DialogContent>
        {setAccess.error && <Alert severity="error">{setAccess.error.message}</Alert>}
        <RadioGroup
          aria-label="Access"
          value={mode}
          onChange={(event) =>
            setMode(event.target.value === "restricted" ? "restricted" : "workspace")
          }
        >
          <FormControlLabel
            value="workspace"
            control={<Radio />}
            label="Everyone in the workspace"
          />
          <FormControlLabel value="restricted" control={<Radio />} label="Only selected members" />
        </RadioGroup>
        {restricted && (
          <List dense aria-label="Members">
            {memberList.map((member) => (
              <ListItem key={member.user_id} disablePadding>
                <FormControlLabel
                  sx={{ width: "100%", mr: 0 }}
                  control={
                    <Checkbox
                      checked={selected.has(member.user_id)}
                      onChange={() => toggle(member.user_id)}
                    />
                  }
                  label={<ListItemText primary={member.name} secondary={member.email} />}
                />
              </ListItem>
            ))}
          </List>
        )}
        {restricted && selected.size === 0 && (
          <FormHelperText error>Select at least one member.</FormHelperText>
        )}
        {leavesSelfOut && selected.size > 0 && (
          <Alert severity="warning">
            You are not selected, so you will lose access to this meeting.
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={close} disabled={setAccess.isPending}>
          Cancel
        </Button>
        <Button
          variant="contained"
          loading={setAccess.isPending}
          disabled={restricted && selected.size === 0}
          onClick={save}
        >
          Save
        </Button>
      </DialogActions>
    </>
  );
}
