import { createFileRoute } from "@tanstack/react-router";
import { Breadcrumbs } from "@/app/layout/Breadcrumbs";
import { SharedMeeting } from "@/features/meetings/sharing/SharedMeeting";
import { PageHeader } from "@/shared/ui/PageHeader";

export const Route = createFileRoute("/_authed/shared/$shareId")({
  component: SharedMeetingRoute,
});

function SharedMeetingRoute() {
  const { shareId } = Route.useParams();
  return (
    <>
      <Breadcrumbs current="Shared meeting" />
      <PageHeader title="Shared meeting" />
      <SharedMeeting shareId={shareId} />
    </>
  );
}
