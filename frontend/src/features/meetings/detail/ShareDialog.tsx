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
  List,
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CopyField } from "@/shared/ui/CopyField";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { type Share, shareQueries, useCreateShare, useRevokeShare } from "../api/shares";

interface ShareDialogProps {
  meetingId: string;
  requestsHref: (shareId: string) => string;
  onClose: () => void;
}

function shareState(share: Share) {
  if (share.revoked_at) return "Revoked";
  if (share.recipient_user_id) return "Shared with an approved recipient";
  return "Waiting for someone to open the link";
}

export function ShareDialog({ meetingId, requestsHref, onClose }: ShareDialogProps) {
  const notify = useNotify();
  const shares = useQuery(shareQueries.list(meetingId));
  const createShare = useCreateShare(meetingId);
  const revokeShare = useRevokeShare(meetingId);
  const [redact, setRedact] = useState(false);
  const pending = createShare.isPending || revokeShare.isPending;

  const create = () => createShare.mutate({ redact_speaker_names: redact });
  const revoke = (shareId: string) =>
    revokeShare.mutate(shareId, { onSuccess: () => notify("Share revoked.") });
  const close = () => {
    if (!pending) onClose();
  };

  return (
    <Dialog open onClose={close} maxWidth="sm" fullWidth>
      <DialogTitle>Share meeting</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Typography color="textSecondary">
            Anyone you send the link to signs in and asks for access. They read the transcript and
            notes only after you approve them, with no recording, export or sharing on.
          </Typography>
          {createShare.error && <Alert severity="error">{createShare.error.message}</Alert>}
          {createShare.data ? (
            <Stack spacing={1}>
              <CopyField value={createShare.data.link} label="Share link" copyLabel="Copy link" />
              <Typography variant="body2" color="textSecondary">
                Copy it now: the link is shown only once.
              </Typography>
            </Stack>
          ) : (
            <FormControlLabel
              control={
                <Checkbox checked={redact} onChange={(event) => setRedact(event.target.checked)} />
              }
              label="Hide speaker names"
            />
          )}
          {revokeShare.error && <Alert severity="error">{revokeShare.error.message}</Alert>}
          {shares.error && <Alert severity="error">{shares.error.message}</Alert>}
          {shares.isLoading && <CircularProgress aria-label="Loading shares" size={24} />}
          {shares.data && shares.data.length > 0 && (
            <List dense aria-label="Your shares">
              {shares.data.map((share) => (
                <ListItem
                  key={share.id}
                  disableGutters
                  secondaryAction={
                    !share.revoked_at && (
                      <Stack direction="row" sx={{ gap: 1 }}>
                        {!share.recipient_user_id && (
                          <Button size="small" href={requestsHref(share.id)}>
                            Requests
                          </Button>
                        )}
                        <Button
                          color="error"
                          size="small"
                          disabled={pending}
                          onClick={() => revoke(share.id)}
                        >
                          Revoke
                        </Button>
                      </Stack>
                    )
                  }
                >
                  <ListItemText
                    primary={shareState(share)}
                    secondary={
                      share.redact_speaker_names ? "Speaker names hidden" : "Speaker names shown"
                    }
                  />
                </ListItem>
              ))}
            </List>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={close} disabled={pending}>
          Close
        </Button>
        {!createShare.data && (
          <Button variant="contained" loading={createShare.isPending} onClick={create}>
            Create link
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
