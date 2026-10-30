import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import { Box, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { meetingQueries } from "../api/meetings";
import type { Meeting } from "../model";

export function RecordingPlayer({ meeting }: { meeting: Meeting }) {
  const { data: link, error } = useQuery(meetingQueries.recording(meeting));

  if (link?.url) {
    return (
      <Box className="player player-ready">
        <video controls src={link.url} aria-label={`${meeting.title} recording`} />
      </Box>
    );
  }
  return (
    <Box className="player">
      <Box className="play-circle">
        <PlayArrowRoundedIcon fontSize="large" />
      </Box>
      <Typography variant="subtitle1">{meeting.title}</Typography>
      {error ? (
        <Typography role="alert">{error.message}</Typography>
      ) : (
        <Typography>
          {meeting.recordingAvailable ? "Loading recording..." : "Recording is not available"}
        </Typography>
      )}
    </Box>
  );
}
