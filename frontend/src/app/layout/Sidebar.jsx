import HomeOutlinedIcon from "@mui/icons-material/HomeOutlined";
import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import NotesOutlinedIcon from "@mui/icons-material/NotesOutlined";
import WorkspacesOutlinedIcon from "@mui/icons-material/WorkspacesOutlined";
import {
  Box,
  Button,
  Card,
  CircularProgress,
  IconButton,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import { IN_PROGRESS_LABELS, isProcessing } from "@/features/meetings/model";
import { NavButton } from "./NavButton";

export function Sidebar({
  user,
  workspaces,
  meetings,
  activeView,
  open,
  onToggleWorkspaces,
  onHome,
  onMeetings,
  onWorkspace,
  onMeeting,
  selectedMeetingId,
  workspaceId,
  onSignOut,
}) {
  const initials = (user?.name ?? "User")
    .split(" ")
    .map((part) => part.charAt(0))
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <Box component="aside" className="sidebar">
      <Typography className="brand">Whadio</Typography>

      <Card className="profile-card">
        <Box className="avatar">{initials}</Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle1" noWrap>
            {user?.name ?? "Signed in"}
          </Typography>
          <Typography color="textSecondary" noWrap>
            {user?.email}
          </Typography>
        </Box>
        <Tooltip title="Sign out" arrow>
          <IconButton size="small" aria-label="Sign out" onClick={onSignOut} sx={{ ml: "auto" }}>
            <LogoutOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Card>

      <Stack component="nav" sx={{ gap: 0.5 }}>
        <NavButton active={activeView === "home"} icon={<HomeOutlinedIcon />} onClick={onHome}>
          Home
        </NavButton>
        <NavButton
          active={activeView === "meetings"}
          icon={<NotesOutlinedIcon />}
          onClick={onMeetings}
        >
          Meetings
        </NavButton>
        <NavButton active={open} icon={<WorkspacesOutlinedIcon />} onClick={onToggleWorkspaces}>
          Workspaces
        </NavButton>

        {open && (
          <Stack className="workspace-tree" sx={{ gap: 0.5 }}>
            {workspaces.map((workspace) => {
              const workspaceMeetings = meetings.filter(
                (item) => item.workspaceId === workspace.id,
              );
              return (
                <Box key={workspace.id}>
                  <Button
                    fullWidth
                    className={
                      workspace.id === workspaceId ? "workspace-node active" : "workspace-node"
                    }
                    onClick={() => onWorkspace(workspace.id)}
                    endIcon={<span className="workspace-count">{workspaceMeetings.length}</span>}
                  >
                    {workspace.name}
                  </Button>
                  <Stack className="transcript-links">
                    {workspaceMeetings.map((meeting) => (
                      <button
                        key={meeting.id}
                        className={
                          meeting.id === selectedMeetingId
                            ? "transcript-link active"
                            : "transcript-link"
                        }
                        type="button"
                        onClick={() => onMeeting(meeting.id)}
                      >
                        <span>{meeting.title}</span>
                        {isProcessing(meeting) && (
                          <small className="nav-processing">
                            <CircularProgress size={11} thickness={5} />
                            {IN_PROGRESS_LABELS[meeting.state]}
                          </small>
                        )}
                      </button>
                    ))}
                  </Stack>
                </Box>
              );
            })}
          </Stack>
        )}
      </Stack>
    </Box>
  );
}
