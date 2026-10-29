import { Box, Card, CardActionArea, Stack, Typography } from "@mui/material";

export function HomeView({ workspaces, meetings, onWorkspace }) {
  return (
    <Stack sx={{ gap: 2 }}>
      <Card className="quiet-panel">
        <Typography variant="h2">Choose a workspace</Typography>
        <Typography color="textSecondary">
          Upload recordings and review processed meetings.
        </Typography>
      </Card>
      <Stack sx={{ gap: 1.5 }}>
        {workspaces.map((workspace) => {
          const workspaceMeetings = meetings.filter((item) => item.workspaceId === workspace.id);
          const active = workspaceMeetings.filter((item) => item.state !== "processed").length;
          return (
            <Card key={workspace.id}>
              <CardActionArea className="workspace-card" onClick={() => onWorkspace(workspace.id)}>
                <Box className="workspace-icon">{workspace.name.charAt(0)}</Box>
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="subtitle1">{workspace.name}</Typography>
                  <Typography color="textSecondary">
                    {workspace.role} · {workspace.members} members
                  </Typography>
                </Box>
                <Typography variant="body2" color="textSecondary">
                  {workspaceMeetings.length} meetings, {active} active
                </Typography>
              </CardActionArea>
            </Card>
          );
        })}
      </Stack>
    </Stack>
  );
}
