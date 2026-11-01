import { Box, Card, CircularProgress, Stack, Typography } from "@mui/material";
import type { NoteRead } from "@/shared/api/types";
import { ErrorBanner } from "@/shared/ui/ErrorBanner";
import { Markdown } from "@/shared/ui/Markdown";
import { describeFailure, IN_PROGRESS_LABELS, isInProgress, type Meeting } from "../model";

interface NotesPanelProps {
  meeting: Meeting;
  notes: NoteRead | null;
  loading: boolean;
  failed: boolean;
}

function NotesContent({ meeting, notes, loading }: Omit<NotesPanelProps, "failed">) {
  if (isInProgress(meeting.state)) {
    return (
      <Stack
        direction="row"
        sx={{
          gap: 1.5,
          alignItems: "center",
          p: "1rem",
          borderRadius: "0.5rem",
          bgcolor: "background.subtle",
        }}
      >
        <CircularProgress size={22} thickness={5} />
        <Box>
          <Typography variant="subtitle1">{IN_PROGRESS_LABELS[meeting.state]}</Typography>
          <Typography color="textSecondary">
            Notes appear here when processing finishes. The transcript appears in its tab as soon as
            it is ready.
          </Typography>
        </Box>
      </Stack>
    );
  }
  if (meeting.state === "failed") {
    return <ErrorBanner>{describeFailure(meeting.failureReason)}</ErrorBanner>;
  }
  if (loading) {
    return (
      <Box sx={{ display: "grid", minHeight: "8rem", placeItems: "center" }}>
        <CircularProgress size={24} />
      </Box>
    );
  }
  if (!notes) {
    return <Typography color="textSecondary">No generated notes are available yet.</Typography>;
  }
  return <Markdown>{notes.content}</Markdown>;
}

export function NotesPanel({ failed, ...props }: NotesPanelProps) {
  if (failed && !props.notes && props.meeting.state === "processed") return null;
  return (
    <Card sx={{ p: { xs: 2, md: 3 } }}>
      <NotesContent {...props} />
    </Card>
  );
}
