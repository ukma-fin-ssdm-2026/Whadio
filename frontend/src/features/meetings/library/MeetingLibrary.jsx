import SearchRoundedIcon from "@mui/icons-material/SearchRounded";
import {
  Box,
  Card,
  CardActionArea,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { formatDate } from "@/shared/lib/format";
import { IN_PROGRESS_LABELS, isProcessing } from "../model";

export function MeetingLibrary({
  title,
  meetings,
  query,
  stateFilter,
  onQuery,
  onStateFilter,
  onMeeting,
  selectedMeetingId,
}) {
  return (
    <Stack sx={{ gap: 1.5 }}>
      <Stack
        direction={{ xs: "column", md: "row" }}
        sx={{
          justifyContent: "space-between",
          alignItems: { xs: "stretch", md: "center" },
          gap: 1.5,
        }}
      >
        <Typography variant="h2">{title}</Typography>
        <Stack direction="row" sx={{ gap: 1 }}>
          <TextField
            size="small"
            placeholder="Filter by name"
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            slotProps={{
              input: { startAdornment: <SearchRoundedIcon color="disabled" sx={{ mr: 1 }} /> },
            }}
          />
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel>State</InputLabel>
            <Select
              label="State"
              value={stateFilter}
              onChange={(event) => onStateFilter(event.target.value)}
            >
              <MenuItem value="all">All states</MenuItem>
              {Object.entries(IN_PROGRESS_LABELS).map(([state, label]) => (
                <MenuItem key={state} value={state}>
                  {label}
                </MenuItem>
              ))}
              <MenuItem value="processed">Processed</MenuItem>
              <MenuItem value="failed">Failed</MenuItem>
            </Select>
          </FormControl>
        </Stack>
      </Stack>

      <Stack sx={{ gap: 1 }}>
        {meetings.map((meeting) => (
          <Card
            key={meeting.id}
            className={meeting.id === selectedMeetingId ? "meeting-row active" : "meeting-row"}
          >
            <CardActionArea className="meeting-row-content" onClick={() => onMeeting(meeting.id)}>
              {isProcessing(meeting) ? (
                <CircularProgress size={16} thickness={5} />
              ) : (
                <Box className="state-dot" />
              )}
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="subtitle1" noWrap>
                  {meeting.title}
                </Typography>
                <Typography color="textSecondary" noWrap>
                  {formatDate(meeting.date)} · {meeting.source}
                  {!isProcessing(meeting) && ` · ${meeting.duration}`}
                </Typography>
              </Box>
              {isProcessing(meeting) && (
                <Box className="processing-status">{IN_PROGRESS_LABELS[meeting.state]}</Box>
              )}
            </CardActionArea>
          </Card>
        ))}
        {meetings.length === 0 && (
          <Card className="empty-state">
            <Typography variant="subtitle1">No meetings found</Typography>
            <Typography color="textSecondary">Try another filter or upload a recording.</Typography>
          </Card>
        )}
      </Stack>
    </Stack>
  );
}
