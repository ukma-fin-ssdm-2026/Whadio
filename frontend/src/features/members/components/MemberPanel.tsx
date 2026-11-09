import PersonRemoveOutlinedIcon from "@mui/icons-material/PersonRemoveOutlined";
import {
  Alert,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  ListItem,
  ListItemText,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { Schemas } from "@/shared/api/types";
import { formatDate, titleCase } from "@/shared/lib/format";
import { canManage } from "@/shared/lib/roles";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { ListPanel } from "@/shared/ui/ListPanel";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { SectionHeader } from "@/shared/ui/SectionHeader";
import {
  type AssignableRole,
  type Member,
  memberQueries,
  useChangeMemberRole,
  useRemoveMember,
} from "../api/members";

const ROLES: AssignableRole[] = ["member", "moderator"];

interface Confirmation {
  kind: "demotion" | "removal";
  member: Member;
  self: boolean;
}

const LOSES_ACCESS = "will lose access to this workspace and all of its meetings.";

function confirmationText({ kind, member, self }: Confirmation) {
  if (kind === "demotion") {
    return {
      title: "Change your role to Member?",
      body: "You will no longer manage members or invitations. Only the Owner or another Moderator can make you a Moderator again.",
      confirmLabel: "Change role",
    };
  }
  return self
    ? { title: "Leave this workspace?", body: `You ${LOSES_ACCESS}`, confirmLabel: "Leave" }
    : {
        title: `Remove ${member.name}?`,
        body: `${member.name} (${member.email}) ${LOSES_ACCESS}`,
        confirmLabel: "Remove",
      };
}

interface ConfirmActionProps {
  workspaceId: string;
  confirmation: Confirmation;
  onLeft: () => void;
  onClose: () => void;
}

function ConfirmAction({ workspaceId, confirmation, onLeft, onClose }: ConfirmActionProps) {
  const changeRole = useChangeMemberRole(workspaceId);
  const remove = useRemoveMember(workspaceId);
  const { kind, member, self } = confirmation;
  const action = kind === "demotion" ? changeRole : remove;
  const { title, body, confirmLabel } = confirmationText(confirmation);

  const confirm = () => {
    if (kind === "demotion") {
      changeRole.mutate({ userId: member.user_id, role: "member", self }, { onSuccess: onClose });
      return;
    }
    remove.mutate(
      { userId: member.user_id, leaving: self },
      {
        onSuccess: () => {
          onClose();
          if (self) onLeft();
        },
      },
    );
  };

  return (
    <ConfirmDialog
      open
      title={title}
      confirmLabel={confirmLabel}
      destructive
      pending={action.isPending}
      onConfirm={confirm}
      onCancel={() => {
        action.reset();
        onClose();
      }}
    >
      {body}
      {action.error && (
        <Typography component="span" color="error" role="alert" sx={{ display: "block", mt: 1 }}>
          {action.error.message}
        </Typography>
      )}
    </ConfirmDialog>
  );
}

interface MemberActionsProps {
  workspaceId: string;
  member: Member;
  self: boolean;
  onConfirm: (confirmation: Confirmation) => void;
}

function MemberActions({ workspaceId, member, self, onConfirm }: MemberActionsProps) {
  const changeRole = useChangeMemberRole(workspaceId);
  const notify = useNotify();
  const removeLabel = self ? "Leave workspace" : `Remove ${member.name}`;

  const chooseRole = (value: string) => {
    const role = ROLES.find((candidate) => candidate === value);
    if (!role) return;
    if (self && role === "member") {
      onConfirm({ kind: "demotion", member, self });
      return;
    }
    changeRole.mutate(
      { userId: member.user_id, role, self },
      { onError: (caught) => notify(caught.message, "error") },
    );
  };

  return (
    <Stack direction="row" sx={{ gap: 1, alignItems: "center", ml: "auto" }}>
      <TextField
        select
        size="small"
        value={member.role}
        disabled={changeRole.isPending}
        onChange={(event) => chooseRole(event.target.value)}
        slotProps={{ htmlInput: { "aria-label": `Role of ${member.name}` } }}
        sx={{ minWidth: 140 }}
      >
        {ROLES.map((role) => (
          <MenuItem key={role} value={role}>
            {titleCase(role)}
          </MenuItem>
        ))}
      </TextField>
      <Tooltip title={removeLabel} arrow>
        <IconButton
          aria-label={removeLabel}
          onClick={() => onConfirm({ kind: "removal", member, self })}
        >
          <PersonRemoveOutlinedIcon />
        </IconButton>
      </Tooltip>
    </Stack>
  );
}

interface MemberPanelProps {
  workspaceId: string;
  myRole: Schemas["Role"];
  currentUserId: string;
  onLeft: () => void;
}

export function MemberPanel({ workspaceId, myRole, currentUserId, onLeft }: MemberPanelProps) {
  const members = useInfiniteQuery(memberQueries.list(workspaceId));
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);

  return (
    <Stack sx={{ gap: 1.5 }}>
      <SectionHeader title="Members" description="Everyone in this workspace and their role." />
      {members.error && <Alert severity="error">{members.error.message}</Alert>}
      {members.isPending ? (
        <CircularProgress size={24} aria-label="Loading members" />
      ) : members.isLoadingError ? null : (
        <ListPanel label="Workspace members">
          {members.data.map((member) => (
            <ListItem key={member.user_id} sx={{ gap: 2, py: 1.5, flexWrap: "wrap" }}>
              <ListItemText
                primary={member.name}
                secondary={`${member.email} · Joined ${formatDate(member.joined_at)}`}
                slotProps={{ primary: { variant: "subtitle1" } }}
                sx={{ overflowWrap: "anywhere", flex: "1 1 12rem" }}
              />
              {canManage(myRole) && member.role !== "owner" ? (
                <MemberActions
                  workspaceId={workspaceId}
                  member={member}
                  self={member.user_id === currentUserId}
                  onConfirm={setConfirmation}
                />
              ) : (
                <Chip label={titleCase(member.role)} size="small" variant="outlined" />
              )}
            </ListItem>
          ))}
        </ListPanel>
      )}
      {members.hasNextPage && (
        <Button disabled={members.isFetchingNextPage} onClick={() => void members.fetchNextPage()}>
          {members.isFetchingNextPage ? "Loading..." : "Load more members"}
        </Button>
      )}
      {confirmation && (
        <ConfirmAction
          workspaceId={workspaceId}
          confirmation={confirmation}
          onLeft={onLeft}
          onClose={() => setConfirmation(null)}
        />
      )}
    </Stack>
  );
}
