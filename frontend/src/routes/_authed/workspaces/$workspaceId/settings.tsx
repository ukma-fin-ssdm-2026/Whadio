import { createFileRoute, useRouter } from "@tanstack/react-router";
import type { WorkspaceDeleteCleanup } from "@/features/workspaces/api/workspaces";
import { WorkspaceSettings } from "@/features/workspaces/components/WorkspaceSettings";

export const Route = createFileRoute("/_authed/workspaces/$workspaceId/settings")({
  component: WorkspaceSettingsRoute,
});

function WorkspaceSettingsRoute() {
  const { workspaceId } = Route.useParams();
  const router = useRouter();
  const deleted = ({ removeFromList, removeDetail }: WorkspaceDeleteCleanup) => {
    const stillOnSettings = router.state.matches.some(({ routeId }) => routeId === Route.id);
    if (!stillOnSettings) {
      removeFromList();
      removeDetail();
      return;
    }
    // Keep the detail cached until Home starts mounting, or this route flashes Page not found.
    const stopWaiting = router.subscribe("onBeforeRouteMount", () => {
      stopWaiting();
      removeFromList();
    });
    void router.navigate({ to: "/" }).then(removeDetail);
  };
  return <WorkspaceSettings workspaceId={workspaceId} onDeleted={deleted} />;
}
