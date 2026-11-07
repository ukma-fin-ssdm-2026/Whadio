import { createFileRoute } from "@tanstack/react-router";
import { WorkspaceSettingsPage } from "@/app/pages/WorkspaceSettingsPage";

export const Route = createFileRoute("/_authed/workspaces/$workspaceId/settings")({
  component: WorkspaceSettingsRoute,
});

function WorkspaceSettingsRoute() {
  const { workspaceId } = Route.useParams();
  return <WorkspaceSettingsPage workspaceId={workspaceId} />;
}
