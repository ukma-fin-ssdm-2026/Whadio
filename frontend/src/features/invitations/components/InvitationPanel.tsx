import DeleteOutlineOutlinedIcon from "@mui/icons-material/DeleteOutlineOutlined";
import PersonAddOutlinedIcon from "@mui/icons-material/PersonAddOutlined";
import {
  Alert,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
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
import { type FormEvent, useState } from "react";
import { formatDate, titleCase } from "@/shared/lib/format";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { CopyField } from "@/shared/ui/CopyField";
import { EmptyState } from "@/shared/ui/EmptyState";
import { ListPanel } from "@/shared/ui/ListPanel";
import { SectionHeader } from "@/shared/ui/SectionHeader";
import {
  type CreatedInvitation,
  type Invitation,
  type InvitedRole,
  invitationQueries,
  useCancelInvitation,
  useCreateInvitation,
} from "../api/invitations";

const ROLES: InvitedRole[] = ["member", "moderator"];

function InviteDialog({ workspaceId, onClose }: { workspaceId: string; onClose: () => void }) {
  const create = useCreateInvitation(workspaceId);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<InvitedRole>("member");
  const [created, setCreated] = useState<CreatedInvitation | null>(null);

  const close = () => {
    create.reset();
    onClose();
  };
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    create.mutate({ email, role }, { onSuccess: setCreated });
  };
  const chooseRole = (value: string) => {
    const nextRole = ROLES.find((candidate) => candidate === value);
    if (nextRole) setRole(nextRole);
  };

  return (
    <Dialog open onClose={create.isPending ? undefined : close} maxWidth="sm" fullWidth>
      <DialogTitle>{created ? "Invitation created" : "Invite a person"}</DialogTitle>
      <DialogContent>
        {created ? (
          <Stack sx={{ gap: 2, pt: 1 }}>
            <Typography>{`The invitation for ${created.email} expires ${formatDate(created.expires_at)}.`}</Typography>
            {created.link ? (
              <>
                <Alert severity="info">
                  This link is shown once. Copy it now and send it to the invited person.
                </Alert>
                <CopyField
                  value={created.link}
                  label="Invitation link"
                  copyLabel="Copy invitation link"
                />
              </>
            ) : (
              <Alert severity="success">The invitation will be delivered by email.</Alert>
            )}
          </Stack>
        ) : (
          <Stack component="form" id="invite-person-form" onSubmit={submit} sx={{ gap: 2, pt: 1 }}>
            <TextField
              label="Email address"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
              autoFocus
            />
            <TextField
              select
              label="Role"
              value={role}
              onChange={(event) => chooseRole(event.target.value)}
            >
              {ROLES.map((value) => (
                <MenuItem key={value} value={value}>
                  {titleCase(value)}
                </MenuItem>
              ))}
            </TextField>
            {create.error && <Alert severity="error">{create.error.message}</Alert>}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        {created ? (
          <Button onClick={close} variant="contained">
            Done
          </Button>
        ) : (
          <>
            <Button onClick={close} disabled={create.isPending}>
              Cancel
            </Button>
            <Button
              type="submit"
              form="invite-person-form"
              variant="contained"
              loading={create.isPending}
            >
              Invite
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}

export function InvitationPanel({ workspaceId }: { workspaceId: string }) {
  const invitations = useInfiniteQuery(invitationQueries.list(workspaceId));
  const cancel = useCancelInvitation(workspaceId);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [invitationToCancel, setInvitationToCancel] = useState<Invitation | null>(null);

  return (
    <Stack sx={{ gap: 1.5 }}>
      <SectionHeader
        title="Invitations"
        description="Invite people as Members or Moderators and manage pending links."
        actions={
          <Button
            variant="contained"
            startIcon={<PersonAddOutlinedIcon />}
            onClick={() => setInviteOpen(true)}
          >
            Invite person
          </Button>
        }
      />
      {invitations.error && <Alert severity="error">{invitations.error.message}</Alert>}
      {invitations.isPending ? (
        <CircularProgress size={24} aria-label="Loading invitations" />
      ) : invitations.isLoadingError ? null : !invitations.data.items.length ? (
        <EmptyState title="No pending invitations" />
      ) : (
        <ListPanel label="Pending invitations">
          {invitations.data.items.map((invitation) => (
            <ListItem
              key={invitation.id}
              secondaryAction={
                <Tooltip title="Cancel invitation" arrow>
                  <IconButton
                    edge="end"
                    aria-label={`Cancel invitation for ${invitation.email}`}
                    onClick={() => setInvitationToCancel(invitation)}
                  >
                    <DeleteOutlineOutlinedIcon />
                  </IconButton>
                </Tooltip>
              }
              sx={{ gap: 2, py: 1.5 }}
            >
              <ListItemText
                primary={invitation.email}
                secondary={`${titleCase(invitation.role)} · Expires ${formatDate(invitation.expires_at)}`}
                slotProps={{ primary: { variant: "subtitle1" } }}
              />
              {!invitation.link_active && <Chip label="Inactive" size="small" variant="outlined" />}
            </ListItem>
          ))}
        </ListPanel>
      )}
      {invitations.hasNextPage && (
        <Button
          disabled={invitations.isFetchingNextPage}
          onClick={() => void invitations.fetchNextPage()}
        >
          {invitations.isFetchingNextPage ? "Loading..." : "Load more invitations"}
        </Button>
      )}
      {inviteOpen && (
        <InviteDialog workspaceId={workspaceId} onClose={() => setInviteOpen(false)} />
      )}
      {invitationToCancel && (
        <ConfirmDialog
          open
          title="Cancel this invitation?"
          confirmLabel="Cancel invitation"
          destructive
          pending={cancel.isPending}
          onConfirm={() =>
            cancel.mutate(invitationToCancel.id, {
              onSuccess: () => setInvitationToCancel(null),
            })
          }
          onCancel={() => {
            cancel.reset();
            setInvitationToCancel(null);
          }}
        >
          {`The link for ${invitationToCancel.email} will stop working.`}
          {cancel.error && (
            <Typography
              component="span"
              color="error"
              role="alert"
              sx={{ display: "block", mt: 1 }}
            >
              {cancel.error.message}
            </Typography>
          )}
        </ConfirmDialog>
      )}
    </Stack>
  );
}
