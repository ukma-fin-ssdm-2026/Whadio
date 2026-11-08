import { Alert, CircularProgress, Paper, Stack } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { sessionQueries } from "@/features/accounts/api/session";
import { InvitationPanel } from "@/features/invitations/components/InvitationPanel";
import { MemberPanel } from "@/features/members/components/MemberPanel";
import { workspaceQueries } from "@/features/workspaces/api/workspaces";
import { canManage } from "@/shared/lib/roles";
import { NotFoundMessage } from "../layout/NotFoundPage";

export function WorkspaceMembersPage({ workspaceId }: { workspaceId: string }) {
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

  return (
    <Stack sx={{ gap: 2 }}>
      <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 } }}>
        <MemberPanel workspaceId={workspaceId} myRole={workspace.my_role} currentUserId={user.id} />
      </Paper>
      {canManage(workspace.my_role) && (
        <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 } }}>
          <InvitationPanel workspaceId={workspaceId} />
        </Paper>
      )}
    </Stack>
  );
}
