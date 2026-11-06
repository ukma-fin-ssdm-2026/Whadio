import { createFileRoute } from "@tanstack/react-router";
import { InvitationPage } from "@/app/pages/InvitationPage";

export const Route = createFileRoute("/invitations/$invitationId")({
  component: InvitationRoute,
});

function InvitationRoute() {
  const { invitationId } = Route.useParams();
  return <InvitationPage invitationId={invitationId} />;
}
