import { createFileRoute } from "@tanstack/react-router";
import { WorkspaceMembersPage } from "@/app/pages/WorkspaceMembersPage";

export const Route = createFileRoute("/_authed/workspaces/$workspaceId/members")({
  component: WorkspaceMembersRoute,
});

function WorkspaceMembersRoute() {
  const { workspaceId } = Route.useParams();
  return <WorkspaceMembersPage workspaceId={workspaceId} />;
}
