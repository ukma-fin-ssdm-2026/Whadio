import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import {
  Box,
  Button,
  Card,
  Chip,
  CircularProgress,
  Divider,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { Fragment } from "react";
import { formatDate, formatTimestamp } from "@/shared/lib/format";
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

  const header = (
    <Stack direction={{ xs: "column", md: "row" }} sx={{ justifyContent: "space-between", gap: 2 }}>
      <Box>
        <Typography variant="h1" sx={{ fontSize: { xs: 34, md: 48 } }}>
          {meeting.title}
        </Typography>
        <Typography className="meeting-date" color="textSecondary">
          {formatDate(meeting.date)} · {meeting.source}
        </Typography>
      </Box>
      <Stack
        className="meeting-meta-actions"
        direction="row"
        sx={{ gap: 0.75, alignItems: "center" }}
      >
        <Fragment key={`${meeting.id}-${tab}-${transcript?.revision.id}`}>
          {exportControls}
        </Fragment>
      </Stack>
    </Stack>
  );

  return (
    <Stack sx={{ gap: 1.5 }}>
      <Tabs value={tab} onChange={(_, value) => onTab(value)} className="meeting-tabs">
        <Tab value="notes" label="Notes" />
        <Tab value="transcript" label="Transcript" />
        <Tab value="recording" label="Recording" />
      </Tabs>

      {tab === "notes" ? (
        <Card className="notes-panel" sx={{ overflow: "visible" }}>
          {header}
          <Divider sx={{ my: 2.5 }} />
          {isProcessing(meeting) ? (
            <Stack
              className="processing-panel"
              direction="row"
              sx={{ gap: 1.5, alignItems: "center" }}
            >
              <CircularProgress size={22} thickness={5} />
              <Box>
                <Typography sx={{ fontWeight: 650 }}>
                  {IN_PROGRESS_LABELS[meeting.state]}
                </Typography>
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
        <Box className="recording-grid">
          {tab === "recording" && (
            <Card className="notes-panel">
              {header}
              <Divider sx={{ my: 2.5 }} />
              {recordingUrl ? (
                <Box className="player player-ready">
                  <video controls src={recordingUrl} aria-label={`${meeting.title} recording`} />
                </Box>
              ) : (
                <Box className="player">
                  <Box className="play-circle">
                    <PlayArrowRoundedIcon fontSize="large" />
                  </Box>
                  <Typography sx={{ fontWeight: 650 }}>{meeting.title}</Typography>
                  <Typography>
                    {meeting.recordingAvailable
                      ? "Loading recording..."
                      : "Recording is not available"}
                  </Typography>
                </Box>
              )}
            </Card>
          )}
          <Card className="transcript-panel" sx={{ overflow: "visible" }}>
            {tab === "transcript" && (
              <>
                {header}
                <Divider sx={{ my: 2.5 }} />
              </>
            )}
            <Stack sx={{ gap: 1.5 }}>
              <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center" }}>
                <Typography variant="h2" sx={{ fontSize: 22 }}>
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
                      <Typography sx={{ fontWeight: 650 }}>{item.speaker}</Typography>
                      <Typography color="primary">{formatTimestamp(item.start_seconds)}</Typography>
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
    </Stack>
  );
}
