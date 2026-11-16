import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useRouter } from "@tanstack/react-router";
import { workspaceQueries } from "@/features/workspaces/api/workspaces";
import { WorkspaceSettings } from "@/features/workspaces/components/WorkspaceSettings";

export const Route = createFileRoute("/_authed/workspaces/$workspaceId/settings")({
  component: WorkspaceSettingsRoute,
});

function WorkspaceSettingsRoute() {
  const { workspaceId } = Route.useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const deleted = () => {
    // Keep the detail cached until Home starts mounting, or this route flashes Page not found.
    const stopWaiting = router.subscribe("onBeforeRouteMount", () => {
      stopWaiting();
      queryClient.setQueryData(
        workspaceQueries.list().queryKey,
        (current) =>
          current && { ...current, items: current.items.filter(({ id }) => id !== workspaceId) },
      );
    });
    void router
      .navigate({ to: "/" })
      .then(() =>
        queryClient.removeQueries({ queryKey: workspaceQueries.detail(workspaceId).queryKey }),
      );
  };
  return <WorkspaceSettings workspaceId={workspaceId} onDeleted={deleted} />;
}
