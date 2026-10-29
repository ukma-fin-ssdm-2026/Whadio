import {
  Avatar,
  ListItem,
  ListItemAvatar,
  ListItemButton,
  ListItemText,
  Stack,
} from "@mui/material";
import { ListPanel } from "@/shared/ui/ListPanel";
import { SectionHeader } from "@/shared/ui/SectionHeader";

export function HomeView({ workspaces, meetings, onWorkspace }) {
  return (
    <Stack sx={{ gap: 1.5 }}>
      <SectionHeader
        title="Choose a workspace"
        description="Upload recordings and review processed meetings."
      />
      <ListPanel>
        {workspaces.map((workspace) => {
          const workspaceMeetings = meetings.filter((item) => item.workspaceId === workspace.id);
          const active = workspaceMeetings.filter((item) => item.state !== "processed").length;
          return (
            <ListItem key={workspace.id} disablePadding>
              <ListItemButton onClick={() => onWorkspace(workspace.id)} sx={{ py: 1.5 }}>
                <ListItemAvatar>
                  <Avatar
                    variant="rounded"
                    sx={{ bgcolor: "tint.main", color: "tint.contrastText" }}
                  >
                    {workspace.name.charAt(0)}
                  </Avatar>
                </ListItemAvatar>
                <ListItemText
                  primary={workspace.name}
                  secondary={`${workspace.role} · ${workspace.members} members · ${workspaceMeetings.length} meetings, ${active} active`}
                  slotProps={{ primary: { variant: "subtitle1" } }}
                />
              </ListItemButton>
            </ListItem>
          );
        })}
      </ListPanel>
    </Stack>
  );
}
