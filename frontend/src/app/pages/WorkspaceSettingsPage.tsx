import { Alert, CircularProgress, Paper, Stack } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { InvitationPanel } from "@/features/invitations/components/InvitationPanel";
import { workspaceQueries } from "@/features/workspaces/api/workspaces";
import { WorkspaceSettings } from "@/features/workspaces/components/WorkspaceSettings";
import { canManage } from "@/shared/lib/roles";

export function WorkspaceSettingsPage({ workspaceId }: { workspaceId: string }) {
  const { data: workspace, error } = useQuery(workspaceQueries.detail(workspaceId));
  if (!workspace) {
    return error ? (
      <Alert severity="error">{error.message}</Alert>
    ) : (
      <CircularProgress aria-label="Loading workspace settings" />
    );
  }

  const canInvite = !workspace.is_personal && canManage(workspace.my_role);

  return (
    <Stack sx={{ gap: 2 }}>
      <WorkspaceSettings workspaceId={workspaceId} />
      {canInvite && (
        <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 } }}>
          <InvitationPanel workspaceId={workspaceId} />
        </Paper>
      )}
    </Stack>
  );
}
