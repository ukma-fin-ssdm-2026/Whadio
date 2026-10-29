import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import {
  Box,
  Button,
  Card,
  Chip,
  CircularProgress,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { Fragment, useId } from "react";
import { formatDate, formatTimestamp } from "@/shared/lib/format";
import { PageHeader } from "@/shared/ui/PageHeader";
import { IN_PROGRESS_LABELS, isProcessing } from "../model";

export function MeetingDetail({
  meeting,
  tab,
  transcriptQuery,
  onTab,
  onTranscriptQuery,
  notes,
  transcript,
  onRevision,
  recordingUrl,
  loading,
  exportControls,
}) {
  const id = useId();
  const speakers = new Map(
    (transcript?.speakers ?? []).map((item) => [item.id, item.display_name]),
  );
  const segments = (transcript?.segments ?? [])
    .map((item) => ({
      ...item,
      speaker: speakers.get(item.speaker_id) ?? "Unknown speaker",
    }))
    .filter(
      (item) =>
        item.text.toLowerCase().includes(transcriptQuery.toLowerCase()) ||
        item.speaker.toLowerCase().includes(transcriptQuery.toLowerCase()),
    );

  const tabProps = (value) => ({ value, id: `${id}-${value}-tab`, "aria-controls": `${id}-panel` });

  return (
    <Stack sx={{ gap: 2 }}>
      <PageHeader
        title={meeting.title}
        description={`${formatDate(meeting.date)} · ${meeting.source}`}
        actions={
          <Fragment key={`${meeting.id}-${tab}-${transcript?.revision.id}`}>
            {exportControls}
          </Fragment>
        }
      />
      <Tabs value={tab} onChange={(_, value) => onTab(value)} className="meeting-tabs">
        <Tab label="Notes" {...tabProps("notes")} />
        <Tab label="Transcript" {...tabProps("transcript")} />
        <Tab label="Recording" {...tabProps("recording")} />
      </Tabs>

      <Box role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${tab}-tab`}>
        {tab === "notes" ? (
          <Card sx={{ p: { xs: 2, md: 3 } }}>
            {isProcessing(meeting) ? (
              <Stack
                className="processing-panel"
                direction="row"
                sx={{ gap: 1.5, alignItems: "center" }}
              >
                <CircularProgress size={22} thickness={5} />
                <Box>
                  <Typography variant="subtitle1">{IN_PROGRESS_LABELS[meeting.state]}</Typography>
                  <Typography color="textSecondary">
                    Transcript and notes appear here when processing finishes.
                  </Typography>
                </Box>
              </Stack>
            ) : meeting.state === "failed" ? (
              <Box className="error-banner" role="alert">
                {meeting.failureReason ?? "Processing failed. Please try another recording."}
              </Box>
            ) : loading ? (
              <Box className="content-loading">
                <CircularProgress size={24} />
              </Box>
            ) : notes ? (
              <Typography component="div" className="notes-text notes-markdown">
                {notes.content}
              </Typography>
            ) : (
              <Typography color="textSecondary">No generated notes are available yet.</Typography>
            )}
          </Card>
        ) : (
          <Box
            sx={{
              display: "grid",
              gap: 2,
              alignItems: "start",
              gridTemplateColumns: {
                md: tab === "recording" ? "minmax(0, 3fr) minmax(0, 2fr)" : "minmax(0, 1fr)",
              },
            }}
          >
            {tab === "recording" &&
              (recordingUrl ? (
                <Box className="player player-ready">
                  <video controls src={recordingUrl} aria-label={`${meeting.title} recording`} />
                </Box>
              ) : (
                <Box className="player">
                  <Box className="play-circle">
                    <PlayArrowRoundedIcon fontSize="large" />
                  </Box>
                  <Typography variant="subtitle1">{meeting.title}</Typography>
                  <Typography>
                    {meeting.recordingAvailable
                      ? "Loading recording..."
                      : "Recording is not available"}
                  </Typography>
                </Box>
              ))}
            <Card sx={{ p: { xs: 2, md: 3 } }}>
              <Stack sx={{ gap: 1.5 }}>
                <Stack
                  direction="row"
                  sx={{ justifyContent: "space-between", alignItems: "center" }}
                >
                  <Typography variant="h2">
                    {transcript?.revision.revision_type === "original"
                      ? "Original transcript"
                      : transcript
                        ? "Edited transcript"
                        : "Transcript"}
                  </Typography>
                  <Chip label={transcript?.segments.length ?? 0} size="small" />
                </Stack>
                {transcript?.is_edited && (
                  <Button
                    onClick={() =>
                      onRevision(
                        transcript.revision.revision_type === "original"
                          ? null
                          : transcript.original_revision_id,
                      )
                    }
                  >
                    {transcript.revision.revision_type === "original"
                      ? "View current transcript"
                      : "View original transcript"}
                  </Button>
                )}
                <TextField
                  size="small"
                  placeholder="Search transcript"
                  value={transcriptQuery}
                  onChange={(event) => onTranscriptQuery(event.target.value)}
                />
                <Stack sx={{ gap: 1.5 }}>
                  {segments.map((item) => (
                    <Box key={item.id} className="transcript-item">
                      <Stack direction="row" sx={{ gap: 1, alignItems: "center" }}>
                        <Box className="speaker-avatar">{item.speaker.slice(-2)}</Box>
                        <Typography variant="subtitle1">{item.speaker}</Typography>
                        <Typography color="primary">
                          {formatTimestamp(item.start_seconds)}
                        </Typography>
                      </Stack>
                      <Typography color="textSecondary">{item.text}</Typography>
                    </Box>
                  ))}
                  {!loading && segments.length === 0 && (
                    <Typography color="textSecondary">
                      {transcript
                        ? "No transcript matches your search."
                        : "Transcript is not available yet."}
                    </Typography>
                  )}
                </Stack>
              </Stack>
            </Card>
          </Box>
        )}
      </Box>
    </Stack>
  );
}
