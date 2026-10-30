import {
  Avatar,
  ListItem,
  ListItemAvatar,
  ListItemButton,
  ListItemText,
  Stack,
} from "@mui/material";
import type { ReactNode } from "react";
import { countOf } from "@/shared/lib/plural";
import { ListPanel } from "@/shared/ui/ListPanel";
import { SectionHeader } from "@/shared/ui/SectionHeader";
import type { Workspace } from "../model";

interface HomeViewProps {
  workspaces: Workspace[];
  renderMeetingFigures: (workspaceId: string) => ReactNode;
  onWorkspace: (id: string) => void;
}

export function HomeView({ workspaces, renderMeetingFigures, onWorkspace }: HomeViewProps) {
  return (
    <Stack sx={{ gap: 1.5 }}>
      <SectionHeader
        title="Choose a workspace"
        description="Upload recordings and review processed meetings."
      />
      <ListPanel>
        {workspaces.map((workspace) => (
          <ListItem key={workspace.id} disablePadding>
            <ListItemButton onClick={() => onWorkspace(workspace.id)} sx={{ py: 1.5 }}>
              <ListItemAvatar>
                <Avatar variant="rounded" sx={{ bgcolor: "tint.main", color: "tint.contrastText" }}>
                  {workspace.name.charAt(0)}
                </Avatar>
              </ListItemAvatar>
              <ListItemText
                primary={workspace.name}
                secondary={
                  <>
                    {workspace.role} · {countOf(workspace.members, "member")} ·{" "}
                    {renderMeetingFigures(workspace.id)}
                  </>
                }
                slotProps={{ primary: { variant: "subtitle1" } }}
              />
            </ListItemButton>
          </ListItem>
        ))}
      </ListPanel>
    </Stack>
  );
}
