import { createFileRoute } from "@tanstack/react-router";
import { WorkspaceSettings } from "@/features/workspaces/components/WorkspaceSettings";

export const Route = createFileRoute("/_authed/workspaces/$workspaceId/settings")({
  component: WorkspaceSettingsRoute,
});

function WorkspaceSettingsRoute() {
  const { workspaceId } = Route.useParams();
  const navigate = Route.useNavigate();
  return <WorkspaceSettings workspaceId={workspaceId} onDeleted={() => navigate({ to: "/" })} />;
}
