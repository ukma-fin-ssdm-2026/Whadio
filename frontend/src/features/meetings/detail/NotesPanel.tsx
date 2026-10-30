import { Box, Card, CircularProgress, Stack, Typography } from "@mui/material";
import type { NoteRead } from "@/shared/api/types";
import { Markdown } from "@/shared/ui/Markdown";
import { IN_PROGRESS_LABELS, isInProgress, type Meeting } from "../model";

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
            Transcript and notes appear here when processing finishes.
          </Typography>
        </Box>
      </Stack>
    );
  }
  if (meeting.state === "failed") {
    return (
      <Box className="error-banner" role="alert">
        {meeting.failureReason ?? "Processing failed. Please try another recording."}
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
  return <Markdown>{notes.content}</Markdown>;
}

export function NotesPanel(props: NotesPanelProps) {
  return (
    <Card sx={{ p: { xs: 2, md: 3 } }}>
      <NotesContent {...props} />
    </Card>
  );
}
