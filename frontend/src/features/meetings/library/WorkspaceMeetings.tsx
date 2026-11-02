import { Button, Stack } from "@mui/material";
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { Schemas } from "@/shared/api/types";
import { meetingQueries } from "../api/meetings";
import { folderQueries } from "../folders/api/folders";
import { WorkspaceFolders } from "../folders/WorkspaceFolders";
import type { StateFilter } from "../model";
import { MeetingLibrary } from "./MeetingLibrary";
import { useNameDraft } from "./useNameDraft";

interface WorkspaceMeetingsProps {
  workspaceId: string;
  workspaceRole: Schemas["Role"];
  selectedMeetingId: string;
  onMeeting: (id: string) => void;
  name: string;
  stateFilter: StateFilter;
  onName: (name: string) => void;
  onStateFilter: (filter: StateFilter) => void;
}

export function WorkspaceMeetings({
  workspaceId,
  workspaceRole,
  selectedMeetingId,
  onMeeting,
  name,
  stateFilter,
  onName,
  onStateFilter,
}: WorkspaceMeetingsProps) {
  const [folderId, setFolderId] = useState<string | null>(null);
  const { draft, type } = useNameDraft(name, onName);
  const folders = useQuery(folderQueries.list(workspaceId));
  const meetings = useInfiniteQuery({
    ...meetingQueries.list(workspaceId, name, folderId),
    placeholderData: keepPreviousData,
  });

  return (
    <Stack sx={{ gap: 3 }}>
      <WorkspaceFolders
        workspaceId={workspaceId}
        role={workspaceRole}
        folders={folders.data ?? []}
        selectedFolderId={folderId}
        loading={folders.isPending}
        error={folders.error?.message}
        onSelect={setFolderId}
      />
      <MeetingLibrary
        title={folders.data?.find((folder) => folder.id === folderId)?.name ?? "Workspace library"}
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
    </Stack>
  );
}
