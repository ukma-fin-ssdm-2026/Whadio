import { Box, Card, CircularProgress, Stack, TextField, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "@/shared/api/errors";
import { ErrorBanner } from "@/shared/ui/ErrorBanner";
import { Markdown } from "@/shared/ui/Markdown";
import { shareQueries } from "../api/shares";
import { SegmentRow } from "../detail/SegmentRow";
import { matchingSegments, NO_MATCH } from "../detail/segments";

function unreadable(error: Error | null) {
  if (!(error instanceof ApiError)) return null;
  if (error.code === "SHARE_REVOKED") return "The person who shared this meeting revoked it.";
  if (error.status === 404) {
    return "This share is not open to your account. If you are a member of the meeting's workspace, open it there.";
  }
  return null;
}

function Loading() {
  return (
    <Box sx={{ display: "grid", minHeight: "8rem", placeItems: "center" }}>
      <CircularProgress size={24} />
    </Box>
  );
}

export function SharedMeeting({ shareId }: { shareId: string }) {
  const transcript = useQuery(shareQueries.transcript(shareId));
  const notes = useQuery(shareQueries.notes(shareId));
  const [query, setQuery] = useState("");

  const blocked = unreadable(transcript.error) ?? unreadable(notes.error);
  if (blocked) return <ErrorBanner>{blocked}</ErrorBanner>;

  const notTranscribed =
    transcript.error instanceof ApiError && transcript.error.code === "NOT_TRANSCRIBED";
  const segments = matchingSegments(transcript.data ?? null, query);

  return (
    <Stack sx={{ gap: 2 }}>
      <Typography color="textSecondary">
        Shared with you to read. The recording, export and sharing are not available.
      </Typography>
      <Card sx={{ p: { xs: 2, md: 3 } }}>
        <Stack sx={{ gap: 1.5 }}>
          <Typography variant="h2">Notes</Typography>
          {notes.isLoading ? (
            <Loading />
          ) : notes.error ? (
            <ErrorBanner>{notes.error.message}</ErrorBanner>
          ) : notes.data ? (
            <Markdown>{notes.data.content}</Markdown>
          ) : (
            <Typography color="textSecondary">No generated notes are available yet.</Typography>
          )}
        </Stack>
      </Card>
      <Card sx={{ p: { xs: 2, md: 3 } }}>
        <Stack sx={{ gap: 1.5 }}>
          <Typography variant="h2">Transcript</Typography>
          {transcript.isLoading ? (
            <Loading />
          ) : notTranscribed ? (
            <Typography color="textSecondary">Transcript is not available yet.</Typography>
          ) : transcript.error ? (
            <ErrorBanner>{transcript.error.message}</ErrorBanner>
          ) : (
            <>
              <TextField
                size="small"
                placeholder="Search transcript"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              {segments.map((item) => (
                <SegmentRow key={item.id} speaker={item.speaker} startSeconds={item.start_seconds}>
                  <Typography color="textSecondary">{item.text}</Typography>
                </SegmentRow>
              ))}
              {segments.length === 0 && (
                <Typography color="textSecondary">
                  {query ? NO_MATCH : "The transcript has no text."}
                </Typography>
              )}
            </>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}
