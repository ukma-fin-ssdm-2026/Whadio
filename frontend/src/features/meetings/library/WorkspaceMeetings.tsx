import { Button } from "@mui/material";
import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { meetingQueries } from "../api/meetings";
import { MeetingLibrary } from "./MeetingLibrary";
import { useMeetingFilters } from "./useMeetingFilters";

interface WorkspaceMeetingsProps {
  workspaceId: string;
  selectedMeetingId: string;
  onMeeting: (id: string) => void;
}

export function WorkspaceMeetings({
  workspaceId,
  selectedMeetingId,
  onMeeting,
}: WorkspaceMeetingsProps) {
  const { name, filters } = useMeetingFilters();
  const meetings = useInfiniteQuery({
    ...meetingQueries.list(workspaceId, name),
    placeholderData: keepPreviousData,
  });

  return (
    <MeetingLibrary
      title="Workspace library"
      meetings={meetings.data ?? []}
      loading={meetings.isPending}
      error={meetings.error?.message}
      selectedMeetingId={selectedMeetingId}
      onMeeting={onMeeting}
      footer={
        meetings.hasNextPage && (
          <Button
            disabled={meetings.isFetchingNextPage}
            onClick={() => meetings.fetchNextPage()}
            sx={{ alignSelf: "center" }}
          >
            {meetings.isFetchingNextPage ? "Loading..." : "Load more"}
          </Button>
        )
      }
      {...filters}
    />
  );
}
