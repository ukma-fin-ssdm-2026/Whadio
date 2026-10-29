import SearchRoundedIcon from "@mui/icons-material/SearchRounded";
import {
  FormControl,
  InputLabel,
  ListItem,
  ListItemButton,
  ListItemText,
  MenuItem,
  Select,
  Stack,
  TextField,
} from "@mui/material";
import { formatDate } from "@/shared/lib/format";
import { EmptyState } from "@/shared/ui/EmptyState";
import { ListPanel } from "@/shared/ui/ListPanel";
import { SectionHeader } from "@/shared/ui/SectionHeader";
import { MeetingStateChip } from "../MeetingStateChip";
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
      <SectionHeader
        title={title}
        actions={
          <>
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
          </>
        }
      />

      {meetings.length === 0 ? (
        <EmptyState title="No meetings found" hint="Try another filter or upload a recording." />
      ) : (
        <ListPanel>
          {meetings.map((meeting) => (
            <ListItem key={meeting.id} disablePadding>
              <ListItemButton
                selected={meeting.id === selectedMeetingId}
                onClick={() => onMeeting(meeting.id)}
                sx={{ gap: 2, py: 1.5 }}
              >
                <ListItemText
                  primary={meeting.title}
                  secondary={`${formatDate(meeting.date)} · ${meeting.source}${
                    isProcessing(meeting) ? "" : ` · ${meeting.duration}`
                  }`}
                  slotProps={{ primary: { noWrap: true, variant: "subtitle1" } }}
                />
                <MeetingStateChip state={meeting.state} />
              </ListItemButton>
            </ListItem>
          ))}
        </ListPanel>
      )}
    </Stack>
  );
}
