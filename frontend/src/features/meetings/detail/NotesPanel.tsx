import { Box, Card, CircularProgress, Stack, Typography } from "@mui/material";
import type { NoteRead } from "@/shared/api/types";
import { describeFailure, IN_PROGRESS_LABELS, isInProgress, type Meeting } from "../model";

interface NotesPanelProps {
  meeting: Meeting;
  notes: NoteRead | null;
  loading: boolean;
}

function NotesContent({ meeting, notes, loading }: NotesPanelProps) {
  if (isInProgress(meeting.state)) {
    return (
      <Stack className="processing-panel" direction="row" sx={{ gap: 1.5, alignItems: "center" }}>
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
    return (
      <Box className="error-banner" role="alert">
        {describeFailure(meeting.failureReason)}
      </Box>
    );
  }
  if (loading) {
    return (
      <Box className="content-loading">
        <CircularProgress size={24} />
      </Box>
    );
  }
  if (!notes) {
    return <Typography color="textSecondary">No generated notes are available yet.</Typography>;
  }
  return (
    <Typography component="div" className="notes-text notes-markdown">
      {notes.content}
    </Typography>
  );
}

export function NotesPanel(props: NotesPanelProps) {
  return (
    <Card sx={{ p: { xs: 2, md: 3 } }}>
      <NotesContent {...props} />
    </Card>
  );
}
