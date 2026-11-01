import { Button } from "@mui/material";
import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { meetingQueries } from "../api/meetings";
import type { StateFilter } from "../model";
import { MeetingLibrary } from "./MeetingLibrary";
import { useNameDraft } from "./useNameDraft";

interface WorkspaceMeetingsProps {
  workspaceId: string;
  selectedMeetingId: string;
  onMeeting: (id: string) => void;
  name: string;
  stateFilter: StateFilter;
  onName: (name: string) => void;
  onStateFilter: (filter: StateFilter) => void;
}

export function WorkspaceMeetings({
  workspaceId,
  selectedMeetingId,
  onMeeting,
  name,
  stateFilter,
  onName,
  onStateFilter,
}: WorkspaceMeetingsProps) {
  const { draft, type } = useNameDraft(name, onName);
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
      query={draft}
      stateFilter={stateFilter}
      onQuery={type}
      onStateFilter={onStateFilter}
    />
  );
}
