import {
  Alert,
  Button,
  Chip,
  CircularProgress,
  ListItem,
  ListItemText,
  MenuItem,
  Stack,
  TextField,
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
} from "../api/members";

const ROLES: AssignableRole[] = ["member", "moderator"];

interface ConfirmDemotionProps {
  workspaceId: string;
  member: Member;
  onClose: () => void;
}

function ConfirmDemotion({ workspaceId, member, onClose }: ConfirmDemotionProps) {
  const changeRole = useChangeMemberRole(workspaceId);

  return (
    <ConfirmDialog
      open
      title="Change your role to Member?"
      confirmLabel="Change role"
      destructive
      pending={changeRole.isPending}
      onConfirm={() =>
        changeRole.mutate(
          { userId: member.user_id, role: "member", self: true },
          { onSuccess: onClose },
        )
      }
      onCancel={() => {
        changeRole.reset();
        onClose();
      }}
    >
      You will no longer manage members or invitations. Only the Owner or another Moderator can make
      you a Moderator again.
      {changeRole.error && (
        <Typography component="span" color="error" role="alert" sx={{ display: "block", mt: 1 }}>
          {changeRole.error.message}
        </Typography>
      )}
    </ConfirmDialog>
  );
}

interface MemberActionsProps {
  workspaceId: string;
  member: Member;
  self: boolean;
  onDemote: (member: Member) => void;
}

function MemberActions({ workspaceId, member, self, onDemote }: MemberActionsProps) {
  const changeRole = useChangeMemberRole(workspaceId);
  const notify = useNotify();

  const chooseRole = (value: string) => {
    const role = ROLES.find((candidate) => candidate === value);
    if (!role) return;
    if (self && role === "member") {
      onDemote(member);
      return;
    }
    changeRole.mutate(
      { userId: member.user_id, role, self },
      { onError: (caught) => notify(caught.message, "error") },
    );
  };

  return (
    <TextField
      select
      size="small"
      value={member.role}
      disabled={changeRole.isPending}
      onChange={(event) => chooseRole(event.target.value)}
      slotProps={{ htmlInput: { "aria-label": `Role of ${member.name}` } }}
      sx={{ minWidth: 140, ml: "auto" }}
    >
      {ROLES.map((role) => (
        <MenuItem key={role} value={role}>
          {titleCase(role)}
        </MenuItem>
      ))}
    </TextField>
  );
}

interface MemberPanelProps {
  workspaceId: string;
  myRole: Schemas["Role"];
  currentUserId: string;
}

export function MemberPanel({ workspaceId, myRole, currentUserId }: MemberPanelProps) {
  const members = useInfiniteQuery(memberQueries.list(workspaceId));
  const [demoting, setDemoting] = useState<Member | null>(null);

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
                  onDemote={setDemoting}
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
      {demoting && (
        <ConfirmDemotion
          workspaceId={workspaceId}
          member={demoting}
          onClose={() => setDemoting(null)}
        />
      )}
    </Stack>
  );
}
