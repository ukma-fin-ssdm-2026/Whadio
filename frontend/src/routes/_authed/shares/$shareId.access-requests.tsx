import { createFileRoute } from "@tanstack/react-router";
import { Breadcrumbs } from "@/app/layout/Breadcrumbs";
import { AccessRequests } from "@/features/meetings/sharing/AccessRequests";
import { PageHeader } from "@/shared/ui/PageHeader";

export const Route = createFileRoute("/_authed/shares/$shareId/access-requests")({
  component: AccessRequestsRoute,
});

function AccessRequestsRoute() {
  const { shareId } = Route.useParams();
  return (
    <>
      <Breadcrumbs current="Access requests" />
      <PageHeader
        title="Access requests"
        description="People who opened your share link and asked to read the meeting. Approving one gives that account access; nobody else can use the link after that."
      />
      <AccessRequests shareId={shareId} />
    </>
  );
}
