import { createFileRoute } from "@tanstack/react-router";
import { useLastMeetingId } from "@/app/navigation/LastMeeting";
import { librarySearch, useLibraryFilters } from "@/app/navigation/library-search";
import { useOpenMeeting } from "@/app/navigation/useOpenMeeting";
import { WorkspaceMeetings } from "@/features/meetings/library/WorkspaceMeetings";
import { UploadPanel } from "@/features/meetings/upload/UploadPanel";
import { WorkspacePresetField } from "@/features/workspaces/components/WorkspacePresetField";

export const Route = createFileRoute("/_authed/workspaces/$workspaceId/")({
  validateSearch: librarySearch,
  component: WorkspaceMeetingsRoute,
});

function WorkspaceMeetingsRoute() {
  const { workspaceId } = Route.useParams();
  const openMeeting = useOpenMeeting();
  return (
    <>
      <UploadPanel
        workspaceId={workspaceId}
        presetField={<WorkspacePresetField workspaceId={workspaceId} />}
        onUploaded={openMeeting}
      />
      <WorkspaceMeetings
        key={workspaceId}
        workspaceId={workspaceId}
        selectedMeetingId={useLastMeetingId()}
        onMeeting={openMeeting}
        {...useLibraryFilters()}
      />
    </>
  );
}
