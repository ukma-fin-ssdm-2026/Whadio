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
import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { formatDate } from "@/shared/lib/format";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { CopyField } from "@/shared/ui/CopyField";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { type Share, shareQueries, useCreateShare, useRevokeShare } from "../api/shares";

interface ShareDialogProps {
  meetingId: string;
  onOpenRequests: (shareId: string) => void;
  onClose: () => void;
}

function shareState(share: Share) {
  if (share.revoked_at) return "Revoked";
  if (share.recipient_user_id) return "Shared with an approved recipient";
  return "No approved recipient yet";
}

export function ShareDialog({ meetingId, onOpenRequests, onClose }: ShareDialogProps) {
  const notify = useNotify();
  const shares = useInfiniteQuery(shareQueries.list(meetingId));
  const createShare = useCreateShare(meetingId);
  const revokeShare = useRevokeShare(meetingId);
  const [redact, setRedact] = useState(false);
  const [shareToRevoke, setShareToRevoke] = useState<Share | null>(null);
  const pending = createShare.isPending || revokeShare.isPending;

  const create = () => createShare.mutate({ redact_speaker_names: redact });
  const revoke = (shareId: string) =>
    revokeShare.mutate(shareId, {
      onSuccess: () => {
        setShareToRevoke(null);
        notify("Share revoked.");
      },
    });
  const close = () => {
    if (!pending) onClose();
  };

  return (
    <>
      <Dialog open onClose={close} maxWidth="sm" fullWidth>
        <DialogTitle>Share meeting</DialogTitle>
        <DialogContent>
          <Stack spacing={2}>
            <Typography color="textSecondary">
              Send the link to someone outside the workspace. They sign in and ask for access, and
              read the transcript and notes only after you approve them. They get no recording,
              export or re-sharing.
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
                  <Checkbox
                    checked={redact}
                    onChange={(event) => setRedact(event.target.checked)}
                  />
                }
                label="Hide speaker names"
              />
            )}
            {shares.error && <Alert severity="error">{shares.error.message}</Alert>}
            {shares.isLoading && <CircularProgress aria-label="Loading shares" size={24} />}
            {shares.data && shares.data.length > 0 && (
              <List dense aria-label="Your shares">
                {shares.data.map((share) => (
                  <ListItem key={share.id} disableGutters sx={{ gap: 1, flexWrap: "wrap" }}>
                    <ListItemText
                      primary={shareState(share)}
                      secondary={`Created ${formatDate(share.created_at)} · ${
                        share.redact_speaker_names ? "Speaker names hidden" : "Speaker names shown"
                      }`}
                      sx={{ flex: "1 1 12rem" }}
                    />
                    {!share.revoked_at && (
                      <Stack direction="row" sx={{ gap: 1 }}>
                        {!share.recipient_user_id && (
                          <Button
                            size="small"
                            aria-label={`Requests for share created ${formatDate(share.created_at)}`}
                            onClick={() => onOpenRequests(share.id)}
                          >
                            Requests
                          </Button>
                        )}
                        <Button
                          color="error"
                          size="small"
                          disabled={pending}
                          aria-label={`Revoke share created ${formatDate(share.created_at)}`}
                          onClick={() => setShareToRevoke(share)}
                        >
                          Revoke
                        </Button>
                      </Stack>
                    )}
                  </ListItem>
                ))}
              </List>
            )}
            {shares.hasNextPage && (
              <Button
                disabled={shares.isFetchingNextPage}
                onClick={() => shares.fetchNextPage()}
                sx={{ alignSelf: "center" }}
              >
                Show more
              </Button>
            )}
            {shares.isFetchingNextPage && (
              <CircularProgress
                aria-label="Loading more shares"
                size={24}
                sx={{ alignSelf: "center" }}
              />
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
      {shareToRevoke && (
        <ConfirmDialog
          open
          title="Revoke this share?"
          confirmLabel="Revoke"
          destructive
          pending={revokeShare.isPending}
          onConfirm={() => revoke(shareToRevoke.id)}
          onCancel={() => {
            revokeShare.reset();
            setShareToRevoke(null);
          }}
        >
          {`The link created ${formatDate(shareToRevoke.created_at)} and its approved recipient lose access at once. This cannot be undone.`}
          {revokeShare.error && (
            <Typography
              component="span"
              color="error"
              role="alert"
              sx={{ display: "block", mt: 1 }}
            >
              {revokeShare.error.message}
            </Typography>
          )}
        </ConfirmDialog>
      )}
    </>
  );
}
