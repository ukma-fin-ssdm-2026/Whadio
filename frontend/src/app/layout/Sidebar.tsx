import HomeOutlinedIcon from "@mui/icons-material/HomeOutlined";
import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import NotesOutlinedIcon from "@mui/icons-material/NotesOutlined";
import {
  Avatar,
  Divider,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  ListSubheader,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import type { ReactNode } from "react";
import type { Page } from "../navigation/page";

interface SidebarProps {
  user: { name?: string | null; email: string } | null;
  workspaces: { id: string; name: string; meetingCount: number }[];
  page: Page;
  workspaceId: string;
  onHome: () => void;
  onMeetings: () => void;
  onWorkspace: (id: string) => void;
  onSignOut: () => void;
  onNavigate: () => void;
}

interface NavItemProps {
  label: string;
  secondary?: string;
  icon?: ReactNode;
  current: boolean;
  onClick: () => void;
}

function NavItem({ label, secondary, icon, current, onClick }: NavItemProps) {
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
        secondary={secondary}
        slotProps={{ primary: { noWrap: true, variant: "subtitle2" } }}
      />
    </ListItemButton>
  );
}

const meetingCount = (count: number) => (count === 1 ? "1 meeting" : `${count} meetings`);

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
  onSignOut,
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
            secondary={meetingCount(workspace.meetingCount)}
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
        <Tooltip title="Sign out" arrow>
          <IconButton size="small" aria-label="Sign out" onClick={onSignOut}>
            <LogoutOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>
    </Stack>
  );
}
