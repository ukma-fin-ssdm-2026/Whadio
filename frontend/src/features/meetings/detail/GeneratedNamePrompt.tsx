import CloseIcon from "@mui/icons-material/Close";
import { Box, Button, IconButton, Stack, Tooltip, Typography } from "@mui/material";
import { useState } from "react";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { useUpdateMeeting } from "../api/meetings";
import type { Meeting } from "../model";
import { RenameMeetingDialog } from "./RenameMeetingDialog";

interface GeneratedNamePromptProps {
  meeting: Meeting;
}

export function GeneratedNamePrompt({ meeting }: GeneratedNamePromptProps) {
  const notify = useNotify();
  const updateMeeting = useUpdateMeeting(meeting.id, meeting.workspaceId);
  const [dismissed, setDismissed] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const asking = meeting.state === "processed" && meeting.nameIsGenerated && !dismissed;

  const keep = () => {
    updateMeeting.mutate(
      { name: meeting.title },
      {
        onSuccess: () => notify("Name kept."),
        onError: (error) => notify(error.message, "error"),
      },
    );
  };

  return (
    <>
      {asking && (
        <Box
          role="group"
          aria-label="Suggested meeting name"
          sx={{
            display: "grid",
            gap: 1,
            alignItems: "center",
            gridTemplateColumns: { xs: "1fr auto", sm: "1fr auto auto" },
            gridTemplateAreas: {
              xs: '"text dismiss" "choices choices"',
              sm: '"text choices dismiss"',
            },
            p: "0.5rem 0.5rem 0.5rem 1rem",
            borderRadius: "0.5rem",
            bgcolor: "background.subtle",
          }}
        >
          <Typography sx={{ gridArea: "text" }}>Whadio suggested this name.</Typography>
          <Stack direction="row" sx={{ gridArea: "choices", gap: 1 }}>
            <Button
              variant="contained"
              size="small"
              loading={updateMeeting.isPending}
              onClick={keep}
            >
              Keep name
            </Button>
            <Button
              size="small"
              disabled={updateMeeting.isPending}
              onClick={() => setRenaming(true)}
            >
              Rename
            </Button>
          </Stack>
          <Tooltip title="Not now" arrow>
            <IconButton
              aria-label="Not now"
              size="small"
              onClick={() => setDismissed(true)}
              sx={{ gridArea: "dismiss" }}
            >
              <CloseIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      )}
      {/* Outside `asking`: saving clears it, and a dialog unmounted mid-save drops its notice. */}
      {renaming && <RenameMeetingDialog meeting={meeting} onClose={() => setRenaming(false)} />}
    </>
  );
}
