import HomeOutlinedIcon from "@mui/icons-material/HomeOutlined";
import NotesOutlinedIcon from "@mui/icons-material/NotesOutlined";
import {
  Avatar,
  Divider,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  ListSubheader,
  Stack,
  Typography,
} from "@mui/material";
import type { ReactNode } from "react";
import type { Page } from "../navigation/page";

interface SidebarProps {
  user: { name?: string | null; email: string } | null;
  workspaces: { id: string; name: string }[];
  page: Page;
  workspaceId: string;
  onHome: () => void;
  onMeetings: () => void;
  onWorkspace: (id: string) => void;
  signOutAction: ReactNode;
  onNavigate: () => void;
}

interface NavItemProps {
  label: string;
  icon?: ReactNode;
  current: boolean;
  onClick: () => void;
}

function NavItem({ label, icon, current, onClick }: NavItemProps) {
  return (
    <ListItemButton
      selected={current}
      aria-current={current ? "page" : undefined}
      onClick={onClick}
      sx={{ borderRadius: 1 }}
    >
      {icon && <ListItemIcon sx={{ minWidth: 36 }}>{icon}</ListItemIcon>}
      <ListItemText
        primary={label}
        slotProps={{ primary: { noWrap: true, variant: "subtitle2" } }}
      />
    </ListItemButton>
  );
}

function initials(name: string) {
  return name
    .split(" ")
    .map((part) => part.charAt(0))
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export function Sidebar({
  user,
  workspaces,
  page,
  workspaceId,
  onHome,
  onMeetings,
  onWorkspace,
  signOutAction,
  onNavigate,
}: SidebarProps) {
  const navigate = (go: () => void) => () => {
    go();
    onNavigate();
  };
  return (
    <Stack sx={{ height: "100%", p: 2, gap: 2 }}>
      <Typography variant="h3" component="p" sx={{ px: 1 }}>
        Whadio
      </Typography>
      <List component="nav" aria-label="Main" sx={{ flexGrow: 1, overflowY: "auto" }}>
        <NavItem
          label="Home"
          icon={<HomeOutlinedIcon />}
          current={page === "home"}
          onClick={navigate(onHome)}
        />
        <NavItem
          label="Meetings"
          icon={<NotesOutlinedIcon />}
          current={page === "meetings"}
          onClick={navigate(onMeetings)}
        />
        <ListSubheader component="div" disableSticky sx={{ mt: 1 }}>
          Workspaces
        </ListSubheader>
        {workspaces.map((workspace) => (
          <NavItem
            key={workspace.id}
            label={workspace.name}
            current={page === "workspace" && workspace.id === workspaceId}
            onClick={navigate(() => onWorkspace(workspace.id))}
          />
        ))}
      </List>
      <Divider />
      <Stack direction="row" sx={{ alignItems: "center", gap: 1.5 }}>
        <Avatar sx={{ bgcolor: "tint.main", color: "tint.contrastText" }}>
          {initials(user?.name ?? "User")}
        </Avatar>
        <ListItemText
          primary={user?.name ?? "Signed in"}
          secondary={user?.email}
          slotProps={{ primary: { noWrap: true }, secondary: { noWrap: true } }}
        />
        {signOutAction}
      </Stack>
    </Stack>
  );
}
