import { Button, Stack } from "@mui/material";
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import type { Schemas } from "@/shared/api/types";
import { folderQueries } from "../api/folders";
import { meetingQueries } from "../api/meetings";
import { recordedRange } from "../dateRange";
import { WorkspaceFolders } from "../folders/WorkspaceFolders";
import type { StateFilter } from "../model";
import { MeetingLibrary } from "./MeetingLibrary";
import { useNameDraft } from "./useNameDraft";

interface WorkspaceMeetingsProps {
  workspaceId: string;
  workspaceRole: Schemas["Role"];
  selectedMeetingId: string;
  onMeeting: (id: string) => void;
  folderId: string | null;
  onFolder: (folderId: string | null) => void;
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

export function WorkspaceMeetings({
  workspaceId,
  workspaceRole,
  selectedMeetingId,
  onMeeting,
  folderId,
  onFolder,
  name,
  stateFilter,
  from,
  to,
  onName,
  onStateFilter,
  onFrom,
  onTo,
  onClear,
}: WorkspaceMeetingsProps) {
  const { draft, type } = useNameDraft(name, onName);
  const range = recordedRange(from, to);
  const unordered = range === "unordered";
  const folders = useQuery(folderQueries.list(workspaceId));
  // A link can name a deleted or malformed folder; it waits for the list and then falls back to all.
  const knownFolder = folders.data?.some((folder) => folder.id === folderId) === true;
  const shownFolderId = knownFolder ? folderId : null;
  const meetings = useInfiniteQuery({
    ...meetingQueries.list(workspaceId, name, shownFolderId, unordered ? {} : range),
    enabled: !unordered && (folderId === null || !folders.isPending),
    placeholderData: keepPreviousData,
  });
  useEffect(() => {
    if (folders.isSuccess && folderId !== null && !knownFolder) onFolder(null);
  }, [folders.isSuccess, folderId, knownFolder, onFolder]);

  return (
    <Stack sx={{ gap: 3 }}>
      <WorkspaceFolders
        workspaceId={workspaceId}
        role={workspaceRole}
        folders={folders.data ?? []}
        selectedFolderId={shownFolderId}
        loading={folders.isPending}
        error={folders.error?.message}
        onSelect={onFolder}
      />
      <MeetingLibrary
        title={
          folders.data?.find((folder) => folder.id === shownFolderId)?.name ?? "Workspace library"
        }
        meetings={unordered ? [] : (meetings.data ?? [])}
        loading={!unordered && meetings.isPending}
        error={unordered ? undefined : meetings.error?.message}
        selectedMeetingId={selectedMeetingId}
        onMeeting={onMeeting}
        footer={
          !unordered &&
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
        from={from}
        to={to}
        rangeUnordered={unordered}
        onFrom={onFrom}
        onTo={onTo}
        onClear={onClear}
      />
    </Stack>
  );
}
