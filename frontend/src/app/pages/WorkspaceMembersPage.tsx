import { Alert, CircularProgress, Paper, Stack } from "@mui/material";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "@tanstack/react-router";
import { sessionQueries } from "@/features/accounts/api/session";
import { InvitationPanel } from "@/features/invitations/components/InvitationPanel";
import { MemberPanel } from "@/features/members/components/MemberPanel";
import { workspaceQueries } from "@/features/workspaces/api/workspaces";
import { canManage } from "@/shared/lib/roles";
import { NotFoundMessage } from "../layout/NotFoundPage";

export function WorkspaceMembersPage({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: workspace, error } = useQuery(workspaceQueries.detail(workspaceId));
  const { data: user } = useQuery(sessionQueries.me());
  if (!workspace || !user) {
    return error ? (
      <Alert severity="error">{error.message}</Alert>
    ) : (
      <CircularProgress aria-label="Loading workspace members" />
    );
  }
  if (workspace.is_personal) return <NotFoundMessage />;

  const leave = () => {
    // The workspace leaves the cached list as Home mounts: earlier, its own route would show
    // Page not found; later, Home would list it and ask for its meetings.
    const stopWaiting = router.subscribe("onBeforeRouteMount", () => {
      stopWaiting();
      queryClient.setQueryData(
        workspaceQueries.list().queryKey,
        (current) =>
          current && { ...current, items: current.items.filter(({ id }) => id !== workspaceId) },
      );
    });
    void router.navigate({ to: "/" });
  };

  return (
    <Stack sx={{ gap: 2 }}>
      <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 } }}>
        <MemberPanel
          workspaceId={workspaceId}
          myRole={workspace.my_role}
          currentUserId={user.id}
          onLeft={leave}
        />
      </Paper>
      {canManage(workspace.my_role) && (
        <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 } }}>
          <InvitationPanel workspaceId={workspaceId} />
        </Paper>
      )}
    </Stack>
  );
}
