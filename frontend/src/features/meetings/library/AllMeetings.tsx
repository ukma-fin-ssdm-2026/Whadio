import { Typography } from "@mui/material";
import { keepPreviousData, useQueries } from "@tanstack/react-query";
import { MEETINGS_PER_PAGE, meetingQueries } from "../api/meetings";
import { recordedRange } from "../dateRange";
import { mapMeeting, type StateFilter } from "../model";
import { MeetingLibrary } from "./MeetingLibrary";
import { useNameDraft } from "./useNameDraft";

interface AllMeetingsProps {
  workspaceIds: string[];
  selectedMeetingId: string;
  onMeeting: (id: string) => void;
  name: string;
  stateFilter: StateFilter;
  from: string;
  to: string;
  onName: (name: string) => void;
  onStateFilter: (filter: StateFilter) => void;
  onFrom: (day: string) => void;
  onTo: (day: string) => void;
  onClear: () => void;
}

export function AllMeetings({
  workspaceIds,
  selectedMeetingId,
  onMeeting,
  name,
  stateFilter,
  from,
  to,
  onName,
  onStateFilter,
  onFrom,
  onTo,
  onClear,
}: AllMeetingsProps) {
  const { draft, type } = useNameDraft(name, onName);
  const range = recordedRange(from, to);
  const unordered = range === "unordered";
  const pages = useQueries({
    queries: workspaceIds.map((workspaceId) => ({
      ...meetingQueries.latest(workspaceId, name, unordered ? {} : range),
      enabled: !unordered,
      placeholderData: keepPreviousData,
    })),
  });
  const meetings = (unordered ? [] : pages)
    .flatMap((page) => page.data?.items ?? [])
    .map(mapMeeting)
    .sort((left, right) => Date.parse(right.date) - Date.parse(left.date));

  return (
    <MeetingLibrary
      title="Workspace library"
      meetings={meetings}
      loading={!unordered && pages.some((page) => page.isPending)}
      error={unordered ? undefined : pages.find((page) => page.error)?.error?.message}
      selectedMeetingId={selectedMeetingId}
      onMeeting={onMeeting}
      footer={
        pages.some((page) => page.data?.pagination.has_more) && (
          <Typography variant="body2" color="textSecondary" sx={{ textAlign: "center" }}>
            Showing the latest {MEETINGS_PER_PAGE} meetings of each workspace. Open a workspace to
            see the rest.
          </Typography>
        )
      }
      query={draft}
      stateFilter={stateFilter}
      onQuery={type}
      onStateFilter={onStateFilter}
      from={from}
      to={to}
      rangeUnordered={unordered}
      onFrom={onFrom}
      onTo={onTo}
      onClear={onClear}
    />
  );
}
