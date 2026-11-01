import SearchRoundedIcon from "@mui/icons-material/SearchRounded";
import {
  Alert,
  CircularProgress,
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
import type { ReactNode } from "react";
import { formatDate } from "@/shared/lib/format";
import { EmptyState } from "@/shared/ui/EmptyState";
import { ListPanel } from "@/shared/ui/ListPanel";
import { SectionHeader } from "@/shared/ui/SectionHeader";
import { MeetingStateChip } from "../MeetingStateChip";
import {
  IN_PROGRESS_LABELS,
  isProcessing,
  type Meeting,
  matchesStateFilter,
  NAME_FILTER_MAX_LENGTH,
  type StateFilter,
} from "../model";

const STATE_OPTIONS: { value: StateFilter; label: string }[] = [
  { value: "all", label: "All states" },
  { value: "recording", label: IN_PROGRESS_LABELS.recording },
  { value: "queued", label: IN_PROGRESS_LABELS.queued },
  { value: "processing", label: IN_PROGRESS_LABELS.processing },
  { value: "processed", label: "Processed" },
  { value: "failed", label: "Failed" },
];

interface MeetingLibraryProps {
  title: string;
  meetings: Meeting[];
  loading?: boolean;
  error?: string;
  query: string;
  stateFilter: StateFilter;
  onQuery: (query: string) => void;
  onStateFilter: (filter: StateFilter) => void;
  onMeeting: (id: string) => void;
  selectedMeetingId: string;
  footer?: ReactNode;
}

export function MeetingLibrary({
  title,
  meetings,
  loading = false,
  error,
  query,
  stateFilter,
  onQuery,
  onStateFilter,
  onMeeting,
  selectedMeetingId,
  footer,
}: MeetingLibraryProps) {
  const visible = meetings.filter((meeting) => matchesStateFilter(meeting, stateFilter));
  const filtered = query.trim() !== "" || stateFilter !== "all";

  const chooseState = (value: string) => {
    const option = STATE_OPTIONS.find((item) => item.value === value);
    if (option) onStateFilter(option.value);
  };

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
                htmlInput: { maxLength: NAME_FILTER_MAX_LENGTH },
              }}
            />
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>State</InputLabel>
              <Select
                label="State"
                value={stateFilter}
                onChange={(event) => chooseState(event.target.value)}
              >
                {STATE_OPTIONS.map(({ value, label }) => (
                  <MenuItem key={value} value={value}>
                    {label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </>
        }
      />

      {error && <Alert severity="error">{error}</Alert>}
      {loading && <CircularProgress aria-label="Loading meetings" sx={{ alignSelf: "center" }} />}
      {!loading && !error && visible.length === 0 && (
        <EmptyState
          title={filtered ? "No meetings match these filters" : "No meetings yet"}
          hint={
            filtered
              ? "Try another name or state."
              : "Upload a recording in a workspace to see it here."
          }
        />
      )}
      {visible.length > 0 && (
        <ListPanel>
          {visible.map((meeting) => (
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
      {footer}
    </Stack>
  );
}
