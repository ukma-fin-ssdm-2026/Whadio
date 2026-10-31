import { Box, Button, Card, Chip, Stack, TextField, Typography } from "@mui/material";
import type { TranscriptRead } from "@/shared/api/types";
import { formatTimestamp } from "@/shared/lib/format";

interface TranscriptPanelProps {
  transcript: TranscriptRead | null;
  missing: boolean;
  loading: boolean;
  query: string;
  onQuery: (query: string) => void;
  onRevision: (revisionId: string | null) => void;
}

function matchingSegments(transcript: TranscriptRead | null, query: string) {
  const speakers = new Map<string | null, string>(
    (transcript?.speakers ?? []).map((item) => [item.id, item.display_name]),
  );
  const wanted = query.toLowerCase();
  return (transcript?.segments ?? [])
    .map((item) => ({
      ...item,
      speaker: speakers.get(item.speaker_id) ?? "Unknown speaker",
    }))
    .filter(
      (item) =>
        item.text.toLowerCase().includes(wanted) || item.speaker.toLowerCase().includes(wanted),
    );
}

export function TranscriptPanel({
  transcript,
  missing,
  loading,
  query,
  onQuery,
  onRevision,
}: TranscriptPanelProps) {
  const segments = matchingSegments(transcript, query);
  const showsOriginal = transcript?.revision.revision_type === "original";

  return (
    <Card sx={{ p: { xs: 2, md: 3 } }}>
      <Stack sx={{ gap: 1.5 }}>
        <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center" }}>
          <Typography variant="h2">
            {showsOriginal
              ? "Original transcript"
              : transcript
                ? "Edited transcript"
                : "Transcript"}
          </Typography>
          <Chip label={transcript?.segments.length ?? 0} size="small" />
        </Stack>
        {transcript?.is_edited && (
          <Button
            onClick={() => onRevision(showsOriginal ? null : transcript.original_revision_id)}
          >
            {showsOriginal ? "View current transcript" : "View original transcript"}
          </Button>
        )}
        <TextField
          size="small"
          placeholder="Search transcript"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
        />
        <Stack sx={{ gap: 1.5 }}>
          {segments.map((item) => (
            <Box key={item.id} className="transcript-item">
              <Stack direction="row" sx={{ gap: 1, alignItems: "center" }}>
                <Box className="speaker-avatar">{item.speaker.slice(-2)}</Box>
                <Typography variant="subtitle1">{item.speaker}</Typography>
                <Typography color="primary">{formatTimestamp(item.start_seconds)}</Typography>
              </Stack>
              <Typography color="textSecondary">{item.text}</Typography>
            </Box>
          ))}
          {!loading && segments.length === 0 && (
            <Typography color="textSecondary">
              {transcript
                ? "No transcript matches your search."
                : missing
                  ? "This meeting has no transcript."
                  : "Transcript is not available yet."}
            </Typography>
          )}
        </Stack>
      </Stack>
    </Card>
  );
}
