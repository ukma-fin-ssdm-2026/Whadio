import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Breadcrumbs } from "@/app/layout/Breadcrumbs";
import { useLastMeetingId } from "@/app/navigation/LastMeeting";
import { useOpenMeeting } from "@/app/navigation/useOpenMeeting";
import { AllMeetings } from "@/features/meetings/library/AllMeetings";
import { workspaceQueries } from "@/features/workspaces/api/workspaces";
import { PageHeader } from "@/shared/ui/PageHeader";

export const Route = createFileRoute("/_authed/meetings/")({ component: MeetingsRoute });

function MeetingsRoute() {
  const openMeeting = useOpenMeeting();
  const { data: workspaces = [] } = useQuery(workspaceQueries.list());
  return (
    <>
      <Breadcrumbs current="Meetings" />
      <PageHeader title="Meetings" />
      <AllMeetings
        workspaceIds={workspaces.map((item) => item.id)}
        selectedMeetingId={useLastMeetingId()}
        onMeeting={openMeeting}
      />
    </>
  );
}
