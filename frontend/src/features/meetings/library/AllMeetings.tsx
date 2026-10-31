import { Typography } from "@mui/material";
import { keepPreviousData, useQueries } from "@tanstack/react-query";
import { MEETINGS_PER_PAGE, meetingQueries } from "../api/meetings";
import { mapMeeting } from "../model";
import { MeetingLibrary } from "./MeetingLibrary";
import { useMeetingFilters } from "./useMeetingFilters";

interface AllMeetingsProps {
  workspaceIds: string[];
  selectedMeetingId: string;
  onMeeting: (id: string) => void;
}

export function AllMeetings({ workspaceIds, selectedMeetingId, onMeeting }: AllMeetingsProps) {
  const { name, filters } = useMeetingFilters();
  const pages = useQueries({
    queries: workspaceIds.map((workspaceId) => ({
      ...meetingQueries.latest(workspaceId, name),
      placeholderData: keepPreviousData,
    })),
  });
  const meetings = pages
    .flatMap((page) => page.data?.items ?? [])
    .map(mapMeeting)
    .sort((left, right) => Date.parse(right.date) - Date.parse(left.date));

  return (
    <MeetingLibrary
      title="Workspace library"
      meetings={meetings}
      loading={pages.some((page) => page.isPending)}
      error={pages.find((page) => page.error)?.error?.message}
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
      {...filters}
    />
  );
}
