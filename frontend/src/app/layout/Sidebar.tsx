import HomeOutlinedIcon from "@mui/icons-material/HomeOutlined";
import NotesOutlinedIcon from "@mui/icons-material/NotesOutlined";
import SmartToyOutlinedIcon from "@mui/icons-material/SmartToyOutlined";
import {
  Avatar,
  Divider,
  List,
  ListItemIcon,
  ListItemText,
  ListSubheader,
  Stack,
  Typography,
} from "@mui/material";
import type { ReactNode } from "react";
import { ListItemLink } from "../navigation/links";

const CURRENT = { selected: true };

interface SidebarProps {
  user: { name?: string | null; email: string } | null;
  workspaces: { id: string; name: string }[];
  signOutAction: ReactNode;
  onNavigate: () => void;
}

function NavLabel({ label, icon }: { label: string; icon?: ReactNode }) {
  return (
    <>
      {icon && <ListItemIcon sx={{ minWidth: 36 }}>{icon}</ListItemIcon>}
      <ListItemText
        primary={label}
        slotProps={{ primary: { noWrap: true, variant: "subtitle2" } }}
      />
    </>
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

export function Sidebar({ user, workspaces, signOutAction, onNavigate }: SidebarProps) {
  const navLink = { activeProps: CURRENT, onClick: onNavigate, sx: { borderRadius: 1 } };
  return (
    <Stack sx={{ height: "100%", p: 2, gap: 2 }}>
      <Typography variant="h3" component="p" sx={{ px: 1 }}>
        Whadio
      </Typography>
      <List component="nav" aria-label="Main" sx={{ flexGrow: 1, overflowY: "auto" }}>
        <ListItemLink to="/" activeOptions={{ exact: true }} {...navLink}>
          <NavLabel label="Home" icon={<HomeOutlinedIcon />} />
        </ListItemLink>
        <ListItemLink to="/meetings" activeOptions={{ exact: true }} {...navLink}>
          <NavLabel label="Meetings" icon={<NotesOutlinedIcon />} />
        </ListItemLink>
        <ListItemLink to="/settings/assistant" {...navLink}>
          <NavLabel label="AI assistant" icon={<SmartToyOutlinedIcon />} />
        </ListItemLink>
        <ListSubheader component="div" disableSticky sx={{ mt: 1 }}>
          Workspaces
        </ListSubheader>
        {workspaces.map((workspace) => (
          <ListItemLink
            key={workspace.id}
            to="/workspaces/$workspaceId"
            params={{ workspaceId: workspace.id }}
            {...navLink}
          >
            <NavLabel label={workspace.name} />
          </ListItemLink>
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
