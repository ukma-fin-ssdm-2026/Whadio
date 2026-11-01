import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import { Box, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { meetingQueries } from "../api/meetings";
import type { Meeting } from "../model";

const playerFrame = {
  display: "grid",
  minHeight: "27rem",
  placeItems: "center",
  alignContent: "center",
  gap: "0.75rem",
  borderRadius: "0.65rem",
  color: "common.white",
  textAlign: "center",
} as const;

const EMPTY_PLAYER_BACKGROUND = `
  radial-gradient(circle at center, rgb(var(--mui-palette-primary-mainChannel) / 34%), transparent 10rem),
  linear-gradient(135deg, transparent 48%, rgb(var(--mui-palette-primary-darkChannel) / 45%)),
  var(--mui-palette-grey-900)`;

export function RecordingPlayer({ meeting }: { meeting: Meeting }) {
  const { data: link, error, refetch } = useQuery(meetingQueries.recording(meeting));
  const resumeAt = useRef<number | null>(null);
  const [unplayableUrl, setUnplayableUrl] = useState<string | null>(null);

  // Every renewal yields a new URL, so counting per URL would loop on a missing file.
  async function renewLink(video: HTMLVideoElement, failedUrl: string) {
    if (resumeAt.current !== null) {
      setUnplayableUrl(failedUrl);
      return;
    }
    resumeAt.current = video.currentTime;
    const { data } = await refetch();
    // An unchanged `src` loads nothing, so no media event would follow.
    if (data?.url === failedUrl) setUnplayableUrl(failedUrl);
  }

  function resume(video: HTMLVideoElement) {
    if (resumeAt.current === null) return;
    video.currentTime = resumeAt.current;
    resumeAt.current = null;
  }

  const unplayable = link?.url === unplayableUrl ? "This recording could not be played." : null;
  const problem = meeting.recordingAvailable ? (error?.message ?? unplayable) : null;

  if (meeting.recordingAvailable && !problem && link?.url) {
    const { url } = link;
    return (
      <Box
        sx={{
          ...playerFrame,
          bgcolor: "common.black",
          "& video": { width: "100%", maxHeight: "34rem" },
        }}
      >
        <video
          controls
          src={url}
          aria-label={`${meeting.title} recording`}
          onError={(event) => renewLink(event.currentTarget, url)}
          onLoadedMetadata={(event) => resume(event.currentTarget)}
        />
      </Box>
    );
  }
  return (
    <Box sx={{ ...playerFrame, background: EMPTY_PLAYER_BACKGROUND }}>
      <Box
        sx={{
          display: "grid",
          width: "4.5rem",
          height: "4.5rem",
          placeItems: "center",
          borderRadius: "999px",
          bgcolor: "color-mix(in srgb, var(--mui-palette-common-white) 16%, transparent)",
        }}
      >
        <PlayArrowRoundedIcon fontSize="large" />
      </Box>
      <Typography variant="subtitle1">{meeting.title}</Typography>
      {problem ? (
        <Typography role="alert">{problem}</Typography>
      ) : (
        <Typography>
          {meeting.recordingAvailable ? "Loading recording..." : "Recording is not available"}
        </Typography>
      )}
    </Box>
  );
}
