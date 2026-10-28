import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import ContentCopyOutlinedIcon from "@mui/icons-material/ContentCopyOutlined";
import DeleteOutlineOutlinedIcon from "@mui/icons-material/DeleteOutlineOutlined";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import GroupsOutlinedIcon from "@mui/icons-material/GroupsOutlined";
import HomeOutlinedIcon from "@mui/icons-material/HomeOutlined";
import KeyOutlinedIcon from "@mui/icons-material/KeyOutlined";
import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import NotesOutlinedIcon from "@mui/icons-material/NotesOutlined";
import PauseRoundedIcon from "@mui/icons-material/PauseRounded";
import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import SearchRoundedIcon from "@mui/icons-material/SearchRounded";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import StopCircleOutlinedIcon from "@mui/icons-material/StopCircleOutlined";
import VideoCameraFrontOutlinedIcon from "@mui/icons-material/VideoCameraFrontOutlined";
import WorkspacesOutlinedIcon from "@mui/icons-material/WorkspacesOutlined";
import {
  Box,
  Button,
  Card,
  CardActionArea,
  Chip,
  CircularProgress,
  CssBaseline,
  createTheme,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  MenuList,
  Paper,
  Select,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  ThemeProvider,
  Tooltip,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ApiError, api } from "./api";
import { meetingLibraryPath, meetingPath, readMeetingLink } from "./meeting-link";
import "./styles.css";
import { formatDuration } from "./format-duration";

const USER_STORAGE_KEY = "whadio-user";

function titleCase(value) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : "";
}

function formatTimestamp(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.floor(seconds % 60);
  return `${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`;
}

function mapWorkspace(item, details = {}) {
  return {
    id: item.id,
    name: item.name,
    role: titleCase(item.my_role),
    members: item.member_count,
    provider: titleCase(item.notes_provider),
    preset: details.default_preset ?? item.default_preset ?? "summary",
  };
}

function mapMeeting(item) {
  return {
    id: item.id,
    workspaceId: item.workspace_id,
    title: item.name,
    date: item.recorded_at,
    state: item.processing_state,
    duration: formatDuration(item.duration_seconds),
    processingEta: item.processing_state === "recording" ? "Recording" : "Processing",
    source: item.source_type === "extension" ? "Google Meet" : "Upload",
    recordingAvailable: item.recording_available ?? false,
    failureReason: item.failure_reason,
  };
}

function isProcessing(meeting) {
  return ["recording", "queued", "processing"].includes(meeting.state);
}

const theme = createTheme({
  palette: {
    background: { default: "#F6F4EF", paper: "#FFFFFF" },
    text: { primary: "#202522", secondary: "#64706A" },
    primary: { main: "#0F766E", dark: "#115E59", light: "#DCEFEB" },
    divider: "#DDE2DC",
    success: { main: "#317451" },
    warning: { main: "#9A6218" },
  },
  shape: { borderRadius: 8 },
  typography: {
    fontFamily:
      'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    h1: { fontWeight: 700, letterSpacing: 0, lineHeight: 1 },
    h2: { fontWeight: 700, letterSpacing: 0 },
    button: { fontWeight: 650, textTransform: "none" },
  },
  components: {
    MuiCard: {
      styleOverrides: {
        root: { border: "1px solid #DDE2DC", boxShadow: "none" },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: { minHeight: 40 },
      },
    },
  },
});

function formatDate(value) {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function App() {
  const [authStatus, setAuthStatus] = useState("loading");
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem(USER_STORAGE_KEY));
    } catch {
      return null;
    }
  });
  const [workspaces, setWorkspaces] = useState([]);
  const [meetings, setMeetings] = useState([]);
  const [error, setError] = useState("");
  const [contentLoading, setContentLoading] = useState(false);
  const [notes, setNotes] = useState(null);
  const [transcript, setTranscript] = useState(null);
  const [recordingUrl, setRecordingUrl] = useState("");
  const [view, setView] = useState("home");
  const [workspaceId, setWorkspaceId] = useState("");
  const [meetingId, setMeetingId] = useState("");
  const [meetingLink, setMeetingLink] = useState(() => readMeetingLink(window.location.href));
  const [workspacesOpen, setWorkspacesOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState("all");
  const [meetingTab, setMeetingTab] = useState("notes");
  const [transcriptQuery, setTranscriptQuery] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [pausedMeetingIds, setPausedMeetingIds] = useState([]);
  const requestedMeetingId = useRef("");

  const loadData = useCallback(async () => {
    const workspacePage = await api.listWorkspaces();
    const workspaceDetails = await Promise.all(
      workspacePage.items.map((item) => api.getWorkspace(item.id)),
    );
    const nextWorkspaces = workspacePage.items.map((item, index) =>
      mapWorkspace(item, workspaceDetails[index]),
    );
    const meetingPages = await Promise.all(nextWorkspaces.map((item) => api.listMeetings(item.id)));
    setWorkspaces(nextWorkspaces);
    const nextMeetings = meetingPages.flatMap((page) => page.items.map(mapMeeting));
    setMeetings((current) => {
      const linked = current.find(
        (item) => item.id === readMeetingLink(window.location.href)?.meetingId,
      );
      const listed =
        linked && !nextMeetings.some((item) => item.id === linked.id)
          ? [...nextMeetings, linked]
          : nextMeetings;
      return listed.map((meeting) => {
        const previous = current.find((item) => item.id === meeting.id);
        return previous?.recordingAvailable
          ? { ...meeting, recordingAvailable: true, failureReason: previous.failureReason }
          : meeting;
      });
    });
    setWorkspaceId((current) => current || nextWorkspaces[0]?.id || "");
    setAuthStatus("signedIn");
  }, []);

  useEffect(() => {
    loadData().catch((caught) => {
      if (caught instanceof ApiError && caught.status === 401) {
        setAuthStatus("signedOut");
        return;
      }
      setError(caught.message);
      setAuthStatus("signedOut");
    });
  }, [loadData]);

  useEffect(() => {
    if (
      authStatus !== "signedIn" ||
      !meetings.some((item) => ["recording", "queued", "processing"].includes(item.state))
    )
      return undefined;
    const timer = window.setInterval(() => {
      loadData().catch((caught) => setError(caught.message));
    }, 10000);
    return () => window.clearInterval(timer);
  }, [authStatus, loadData, meetings]);

  const workspace = workspaces.find((item) => item.id === workspaceId) ?? workspaces[0];
  const selectedMeeting = meetings.find((item) => item.id === meetingId);

  const visibleMeetings = useMemo(() => {
    const source =
      view === "meetings" ? meetings : meetings.filter((item) => item.workspaceId === workspaceId);

    return source
      .filter((item) => item.title.toLowerCase().includes(query.toLowerCase()))
      .filter(
        (item) =>
          stateFilter === "all" ||
          (stateFilter === "queued" ? isProcessing(item) : item.state === stateFilter),
      )
      .sort((left, right) => new Date(right.date) - new Date(left.date));
  }, [meetings, query, stateFilter, view, workspaceId]);

  const loadMeetingContent = useCallback(async (id, revisionId = null) => {
    const request = {};
    requestedMeetingId.current = request;
    setContentLoading(true);
    setError("");
    setNotes(null);
    setTranscript(null);
    setRecordingUrl("");
    try {
      const detail = await api.getMeeting(id);
      if (requestedMeetingId.current !== request) return;
      const mapped = mapMeeting(detail);
      setWorkspaceId(mapped.workspaceId);
      setMeetings((items) => [mapped, ...items.filter((item) => item.id !== id)]);
      const [notesResult, transcriptResult] = await Promise.allSettled([
        api.listNotes(id),
        api.getTranscript(id, revisionId),
      ]);
      if (requestedMeetingId.current !== request) return;
      if (notesResult.status === "fulfilled") setNotes(notesResult.value.items[0] ?? null);
      if (transcriptResult.status === "fulfilled") {
        setTranscript(transcriptResult.value);
      } else if (transcriptResult.reason.code !== "NOT_TRANSCRIBED" || revisionId) {
        setError(transcriptResult.reason.message);
      }
      if (notesResult.status === "rejected") setError(notesResult.reason.message);
    } catch (caught) {
      if (requestedMeetingId.current === request) {
        setMeetings((items) => items.filter((item) => item.id !== id));
        setError(caught.message);
      }
    } finally {
      if (requestedMeetingId.current === request) setContentLoading(false);
    }
  }, []);

  useEffect(() => {
    const followHistory = (event) => {
      const linked = readMeetingLink(window.location.href);
      setMeetingLink(linked ? { ...linked, tab: event.state?.tab } : null);
      setView("meetings");
    };
    window.addEventListener("popstate", followHistory);
    return () => window.removeEventListener("popstate", followHistory);
  }, []);

  useEffect(() => {
    if (authStatus !== "signedIn" || !meetingLink) return;
    setMeetingId(meetingLink.meetingId);
    setMeetingTab(meetingLink.tab ?? (meetingLink.revisionId ? "transcript" : "notes"));
    setTranscriptQuery("");
    setSettingsOpen(false);
    setView("meeting");
    loadMeetingContent(meetingLink.meetingId, meetingLink.revisionId);
    return () => {
      requestedMeetingId.current = "";
    };
  }, [authStatus, meetingLink, loadMeetingContent]);

  const clearMeetingLink = () => {
    window.history.pushState(null, "", meetingLibraryPath(window.location.href));
    setMeetingLink(null);
    requestedMeetingId.current = "";
  };

  const openWorkspace = (id) => {
    clearMeetingLink();
    requestedMeetingId.current = "";
    setWorkspaceId(id);
    setMeetingId("");
    setQuery("");
    setStateFilter("all");
    setWorkspacesOpen(true);
    setSettingsOpen(false);
    setView("workspace");
  };

  const openMeeting = (id, revisionId = null, tab = null) => {
    window.history.pushState({ tab }, "", meetingPath(window.location.href, id, revisionId));
    setMeetingLink({ ...readMeetingLink(window.location.href), tab });
    setWorkspacesOpen(true);
  };

  const showRecording = async () => {
    setMeetingTab("recording");
    if (!recordingUrl && selectedMeeting?.recordingAvailable) {
      try {
        const playback = await api.getRecording(selectedMeeting.id);
        setRecordingUrl(playback.url);
      } catch (caught) {
        setError(caught.message);
      }
    }
  };

  const showMeetings = () => {
    clearMeetingLink();
    requestedMeetingId.current = "";
    setView("meetings");
    setMeetingId("");
    setQuery("");
    setStateFilter("all");
    setSettingsOpen(false);
  };

  const toggleProcessing = (id) => {
    setPausedMeetingIds((ids) =>
      ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id],
    );
  };

  const title =
    view === "home"
      ? "Workspaces"
      : view === "meetings"
        ? "Meetings"
        : view === "meeting"
          ? (selectedMeeting?.title ?? "Meeting")
          : (workspace?.name ?? "Workspace");

  const handleSignIn = async (email, password) => {
    setError("");
    const session = await api.signIn(email, password);
    setUser(session.user);
    sessionStorage.setItem(USER_STORAGE_KEY, JSON.stringify(session.user));
    setAuthStatus("loading");
    await loadData();
  };

  const handleSignOut = async () => {
    try {
      await api.signOut();
    } finally {
      requestedMeetingId.current = "";
      sessionStorage.removeItem(USER_STORAGE_KEY);
      setUser(null);
      setWorkspaces([]);
      setMeetings([]);
      setAuthStatus("signedOut");
    }
  };

  const handleUpload = async (payload) => {
    const created = await api.uploadMeeting(workspaceId, payload);
    const mapped = mapMeeting(created);
    setMeetings((items) => [mapped, ...items]);
    setMeetingId(mapped.id);
    setMeetingTab("notes");
    setTranscriptQuery("");
    setWorkspacesOpen(true);
    setSettingsOpen(false);
    setView("meeting");
    openMeeting(mapped.id);
  };

  if (authStatus !== "signedIn") {
    return (
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {authStatus === "loading" ? (
          <Box className="auth-screen">
            <CircularProgress />
          </Box>
        ) : (
          <SignIn onSubmit={handleSignIn} externalError={error} />
        )}
      </ThemeProvider>
    );
  }

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box className="app-shell">
        <Sidebar
          user={user}
          workspaces={workspaces}
          meetings={meetings}
          activeView={view}
          open={workspacesOpen}
          onToggleWorkspaces={() => setWorkspacesOpen((value) => !value)}
          onHome={() => {
            clearMeetingLink();
            setSettingsOpen(false);
            setView("home");
          }}
          onMeetings={showMeetings}
          onWorkspace={openWorkspace}
          onMeeting={openMeeting}
          selectedMeetingId={meetingId}
          workspaceId={workspaceId}
          pausedMeetingIds={pausedMeetingIds}
          onSignOut={handleSignOut}
        />

        <Box component="main" className="main">
          <Breadcrumbs
            view={view}
            workspace={workspace}
            meeting={selectedMeeting}
            onHome={() => {
              clearMeetingLink();
              setView("home");
            }}
            onWorkspace={openWorkspace}
          />

          {view !== "meeting" && (
            <Stack
              direction="row"
              className="page-header"
              sx={{ justifyContent: "space-between", alignItems: "flex-end", gap: 2 }}
            >
              <Box>
                {view === "workspace" && (
                  <Typography className="eyebrow">{workspace.role} workspace</Typography>
                )}
                <Typography variant="h1" sx={{ fontSize: { xs: 36, md: 52 } }}>
                  {title}
                </Typography>
              </Box>
              {view === "workspace" && (
                <Tooltip title="Workspace settings" arrow>
                  <IconButton
                    className={settingsOpen ? "settings-button active" : "settings-button"}
                    aria-label="Workspace settings"
                    onClick={() => setSettingsOpen((value) => !value)}
                  >
                    <SettingsOutlinedIcon />
                  </IconButton>
                </Tooltip>
              )}
            </Stack>
          )}

          {error && (
            <Box className="error-banner" role="alert">
              {error}
            </Box>
          )}
          {view === "home" && (
            <HomeView workspaces={workspaces} meetings={meetings} onWorkspace={openWorkspace} />
          )}
          {view === "workspace" && settingsOpen && <WorkspaceSettings workspace={workspace} />}
          {view === "workspace" && !settingsOpen && (
            <>
              <UploadPanel workspace={workspace} onUpload={handleUpload} />
              <MeetingLibrary
                title="Workspace library"
                meetings={visibleMeetings}
                query={query}
                stateFilter={stateFilter}
                onQuery={setQuery}
                onStateFilter={setStateFilter}
                onMeeting={openMeeting}
                selectedMeetingId={meetingId}
                pausedMeetingIds={pausedMeetingIds}
                onToggleProcessing={toggleProcessing}
              />
            </>
          )}
          {view === "meetings" && (
            <MeetingLibrary
              title="Workspace library"
              meetings={visibleMeetings}
              query={query}
              stateFilter={stateFilter}
              onQuery={setQuery}
              onStateFilter={setStateFilter}
              onMeeting={openMeeting}
              selectedMeetingId={meetingId}
              pausedMeetingIds={pausedMeetingIds}
              onToggleProcessing={toggleProcessing}
            />
          )}
          {view === "meeting" && selectedMeeting && (
            <MeetingDetail
              meeting={selectedMeeting}
              workspace={workspace}
              tab={meetingTab}
              transcriptQuery={transcriptQuery}
              onTranscriptQuery={setTranscriptQuery}
              onTab={(value) => (value === "recording" ? showRecording() : setMeetingTab(value))}
              notes={notes}
              transcript={transcript}
              onRevision={(revisionId) => openMeeting(selectedMeeting.id, revisionId, "transcript")}
              recordingUrl={recordingUrl}
              loading={contentLoading}
              paused={pausedMeetingIds.includes(selectedMeeting.id)}
              onToggleProcessing={() => toggleProcessing(selectedMeeting.id)}
            />
          )}
        </Box>
      </Box>
    </ThemeProvider>
  );
}

function SignIn({ onSubmit, externalError }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await onSubmit(email, password);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Box className="auth-screen">
      <Card component="form" className="auth-card" onSubmit={submit}>
        <Typography className="brand">Whadio</Typography>
        <Box>
          <Typography variant="h1" sx={{ fontSize: 32 }}>
            Sign in
          </Typography>
          <Typography color="textSecondary">Open your meetings, notes, and transcripts.</Typography>
        </Box>
        <TextField
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <TextField
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {(error || externalError) && (
          <Typography color="error" role="alert">
            {error || externalError}
          </Typography>
        )}
        <Button type="submit" variant="contained" disabled={submitting}>
          {submitting ? "Signing in..." : "Sign in"}
        </Button>
      </Card>
    </Box>
  );
}

function Sidebar({
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
  pausedMeetingIds,
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
          <Typography noWrap sx={{ fontWeight: 650 }}>
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
                        {["recording", "queued", "processing"].includes(meeting.state) && (
                          <small
                            className={
                              pausedMeetingIds.includes(meeting.id)
                                ? "nav-processing paused"
                                : "nav-processing"
                            }
                          >
                            {pausedMeetingIds.includes(meeting.id) ? (
                              <>
                                <StopCircleOutlinedIcon sx={{ fontSize: 14 }} />
                                Paused
                              </>
                            ) : (
                              <>
                                <CircularProgress size={11} thickness={5} />
                                {meeting.processingEta}
                              </>
                            )}
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

function NavButton({ active, icon, onClick, children }) {
  return (
    <Button
      fullWidth
      startIcon={icon}
      className={active ? "nav-button active" : "nav-button"}
      onClick={onClick}
    >
      {children}
    </Button>
  );
}

function Breadcrumbs({ view, workspace, meeting, onHome, onWorkspace }) {
  if (view === "home") return <Box className="breadcrumbs" />;
  return (
    <Stack direction="row" className="breadcrumbs" sx={{ alignItems: "center", gap: 1 }}>
      <button type="button" onClick={onHome}>
        Home
      </button>
      <span>/</span>
      {view === "meetings" ? (
        <span>Meetings</span>
      ) : (
        <button type="button" onClick={() => onWorkspace(workspace.id)}>
          {workspace.name}
        </button>
      )}
      {view === "meeting" && meeting && (
        <>
          <span>/</span>
          <span>{meeting.title}</span>
        </>
      )}
    </Stack>
  );
}

function HomeView({ workspaces, meetings, onWorkspace }) {
  return (
    <Stack sx={{ gap: 2 }}>
      <Card className="quiet-panel">
        <Typography variant="h2" sx={{ fontSize: 24 }}>
          Choose a workspace
        </Typography>
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
                  <Typography sx={{ fontWeight: 650 }}>{workspace.name}</Typography>
                  <Typography color="textSecondary">
                    {workspace.role} · {workspace.members} members
                  </Typography>
                </Box>
                <Typography color="textSecondary" sx={{ fontWeight: 650 }}>
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

function UploadPanel({ workspace, onUpload }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [file, setFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!file) {
      setError("Select an audio or video file.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await onUpload({ file, name });
      setOpen(false);
      setName("");
      setFile(null);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card className="upload-panel">
      <Stack
        direction={{ xs: "column", sm: "row" }}
        sx={{
          gap: 1.5,
          justifyContent: "space-between",
          alignItems: { xs: "stretch", sm: "center" },
        }}
      >
        <Box>
          <Typography variant="h2" sx={{ fontSize: 18, fontWeight: 650 }}>
            Upload recording
          </Typography>
          <Typography color="textSecondary" sx={{ fontSize: 14 }}>
            Queue audio or video for processing.
          </Typography>
        </Box>
        <Button
          variant="contained"
          startIcon={<CloudUploadOutlinedIcon />}
          onClick={() => setOpen(true)}
        >
          Upload
        </Button>
      </Stack>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Upload recording</DialogTitle>
        <DialogContent>
          <Stack sx={{ gap: 2, pt: 0.5 }}>
            <TextField
              label="Meeting name"
              placeholder="Lab 3 architecture planning"
              value={name}
              onChange={(event) => setName(event.target.value)}
              fullWidth
            />
            <FormControl fullWidth>
              <InputLabel>Note preset</InputLabel>
              <Select label="Note preset" value={workspace.preset} disabled>
                <MenuItem value={workspace.preset}>
                  {titleCase(workspace.preset)} (workspace default)
                </MenuItem>
              </Select>
            </FormControl>
            <Button
              className="file-picker-button"
              component="label"
              variant="outlined"
              startIcon={<CloudUploadOutlinedIcon />}
            >
              {file?.name ?? "Select file"}
              <input
                hidden
                type="file"
                accept="audio/*,video/*"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </Button>
            {error && (
              <Typography color="error" role="alert">
                {error}
              </Typography>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" disabled={submitting} onClick={submit}>
            {submitting ? "Uploading..." : "Queue processing"}
          </Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}

function WorkspaceSettings({ workspace }) {
  const [section, setSection] = useState("workspace");

  return (
    <Card className="settings-panel">
      <Box className="settings-nav">
        <Typography className="eyebrow">Settings</Typography>
        <button
          className={section === "workspace" ? "settings-nav-item active" : "settings-nav-item"}
          type="button"
          onClick={() => setSection("workspace")}
        >
          Workspace
        </button>
        <button
          className={section === "assistant" ? "settings-nav-item active" : "settings-nav-item"}
          type="button"
          onClick={() => setSection("assistant")}
        >
          AI assistant
        </button>
      </Box>

      {section === "workspace" ? (
        <Stack className="settings-options" sx={{ gap: 1.25 }}>
          <Box>
            <Typography variant="h2" sx={{ fontSize: 24 }}>
              Workspace settings
            </Typography>
            <Typography color="textSecondary">
              Configure processing defaults for {workspace.name}.
            </Typography>
          </Box>

          <Card className="settings-option-card">
            <Stack
              direction={{ xs: "column", md: "row" }}
              sx={{ justifyContent: "space-between", gap: 2 }}
            >
              <Box>
                <Typography sx={{ fontWeight: 650 }}>Notes provider</Typography>
                <Typography color="textSecondary">
                  Whadio gemma-3-12b-it is used for generated notes.
                </Typography>
              </Box>
              <Chip label={workspace.provider} variant="outlined" />
            </Stack>
          </Card>

          <Card className="settings-option-card">
            <Stack
              direction={{ xs: "column", md: "row" }}
              sx={{ justifyContent: "space-between", gap: 2 }}
            >
              <Box>
                <Typography sx={{ fontWeight: 650 }}>Workspace access</Typography>
                <Typography color="textSecondary">
                  Members of this workspace can open processed meetings.
                </Typography>
              </Box>
              <Switch defaultChecked color="primary" />
            </Stack>
          </Card>

          <Card className="settings-option-card">
            <Stack
              direction={{ xs: "column", md: "row" }}
              sx={{ justifyContent: "space-between", gap: 2 }}
            >
              <Box>
                <Typography sx={{ fontWeight: 650 }}>Default notes preset</Typography>
                <Typography color="textSecondary">
                  New uploads use the workspace notes preset.
                </Typography>
              </Box>
              <Chip label={titleCase(workspace.preset)} variant="outlined" />
            </Stack>
          </Card>
        </Stack>
      ) : (
        <McpKeySettings />
      )}
    </Card>
  );
}

function McpKeySettings() {
  const [keys, setKeys] = useState([]);
  const [expiresInDays, setExpiresInDays] = useState(30);
  const [secret, setSecret] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const loadKeys = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const page = await api.listMcpKeys();
      setKeys(page.items);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadKeys();
  }, [loadKeys]);

  const createKey = async () => {
    setSubmitting(true);
    setError("");
    try {
      const created = await api.createMcpKey(expiresInDays || null);
      const { secret: createdSecret, ...key } = created;
      setSecret(createdSecret);
      setKeys((current) => [key, ...current]);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSubmitting(false);
    }
  };

  const revokeKey = async (keyId) => {
    setError("");
    try {
      await api.revokeMcpKey(keyId);
      await loadKeys();
    } catch (caught) {
      setError(caught.message);
    }
  };

  return (
    <Stack className="settings-options" sx={{ gap: 1.25 }}>
      <Box>
        <Typography variant="h2" sx={{ fontSize: 24 }}>
          AI assistant access
        </Typography>
        <Typography color="textSecondary">
          Use a personal key to connect an assistant to meetings you can access.
        </Typography>
      </Box>

      <Card className="settings-option-card">
        <Stack
          direction={{ xs: "column", sm: "row" }}
          sx={{ alignItems: { sm: "center" }, gap: 1.25 }}
        >
          <FormControl size="small" sx={{ minWidth: 180 }}>
            <InputLabel>Expires</InputLabel>
            <Select
              label="Expires"
              value={expiresInDays}
              onChange={(event) => setExpiresInDays(event.target.value)}
            >
              <MenuItem value="">Never</MenuItem>
              <MenuItem value={30}>30 days</MenuItem>
              <MenuItem value={90}>90 days</MenuItem>
              <MenuItem value={365}>1 year</MenuItem>
            </Select>
          </FormControl>
          <Button
            variant="contained"
            startIcon={<KeyOutlinedIcon />}
            disabled={submitting}
            onClick={createKey}
          >
            {submitting ? "Creating..." : "Create key"}
          </Button>
        </Stack>
      </Card>

      {error && (
        <Typography color="error" role="alert">
          {error}
        </Typography>
      )}
      {loading ? (
        <CircularProgress size={24} />
      ) : (
        <Stack sx={{ gap: 1 }}>
          {keys.length === 0 && (
            <Typography color="textSecondary">No assistant keys yet.</Typography>
          )}
          {keys.map((key) => (
            <Box className="mcp-key-row" key={key.id}>
              <KeyOutlinedIcon color={key.is_active ? "primary" : "disabled"} />
              <Box sx={{ minWidth: 0 }}>
                <Typography sx={{ fontWeight: 600 }}>Key {key.id.slice(0, 8)}</Typography>
                <Typography color="textSecondary" sx={{ fontSize: 14 }}>
                  Created {formatDate(key.created_at)} ·{" "}
                  {key.expires_at ? `Expires ${formatDate(key.expires_at)}` : "Never expires"}
                </Typography>
              </Box>
              <Chip
                size="small"
                label={key.is_active ? "Active" : key.revoked_at ? "Revoked" : "Expired"}
                color={key.is_active ? "success" : "default"}
                variant="outlined"
              />
              {key.is_active && (
                <Tooltip title="Revoke key" arrow>
                  <IconButton aria-label="Revoke key" onClick={() => revokeKey(key.id)}>
                    <DeleteOutlineOutlinedIcon />
                  </IconButton>
                </Tooltip>
              )}
            </Box>
          ))}
        </Stack>
      )}

      <Dialog open={Boolean(secret)} onClose={() => setSecret("")} fullWidth maxWidth="sm">
        <DialogTitle>Save your MCP key</DialogTitle>
        <DialogContent>
          <Stack sx={{ gap: 2, pt: 1 }}>
            <Typography color="textSecondary">
              This secret is shown once. Store it securely before closing this window.
            </Typography>
            <TextField
              value={secret}
              slotProps={{
                htmlInput: { readOnly: true, "aria-label": "MCP key secret" },
                input: {
                  endAdornment: (
                    <Tooltip title="Copy key" arrow>
                      <IconButton
                        aria-label="Copy key"
                        onClick={() => navigator.clipboard.writeText(secret)}
                      >
                        <ContentCopyOutlinedIcon />
                      </IconButton>
                    </Tooltip>
                  ),
                },
              }}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button variant="contained" onClick={() => setSecret("")}>
            Done
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

function MeetingLibrary({
  title,
  meetings,
  query,
  stateFilter,
  onQuery,
  onStateFilter,
  onMeeting,
  selectedMeetingId,
  pausedMeetingIds,
  onToggleProcessing,
}) {
  return (
    <Stack sx={{ gap: 1.5 }}>
      <Stack
        direction={{ xs: "column", md: "row" }}
        sx={{
          justifyContent: "space-between",
          alignItems: { xs: "stretch", md: "center" },
          gap: 1.5,
        }}
      >
        <Typography variant="h2" sx={{ fontSize: 22 }}>
          {title}
        </Typography>
        <Stack direction="row" sx={{ gap: 1 }}>
          <TextField
            size="small"
            placeholder="Filter by name"
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            slotProps={{
              input: { startAdornment: <SearchRoundedIcon color="disabled" sx={{ mr: 1 }} /> },
            }}
          />
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel>State</InputLabel>
            <Select
              label="State"
              value={stateFilter}
              onChange={(event) => onStateFilter(event.target.value)}
            >
              <MenuItem value="all">All states</MenuItem>
              <MenuItem value="processed">Processed</MenuItem>
              <MenuItem value="queued">Processing</MenuItem>
              <MenuItem value="processing">Transcribing</MenuItem>
              <MenuItem value="recording">Recording</MenuItem>
              <MenuItem value="failed">Failed</MenuItem>
            </Select>
          </FormControl>
        </Stack>
      </Stack>

      <Stack sx={{ gap: 1 }}>
        {meetings.map((meeting) => (
          <Card
            key={meeting.id}
            className={meeting.id === selectedMeetingId ? "meeting-row active" : "meeting-row"}
          >
            <CardActionArea className="meeting-row-content" onClick={() => onMeeting(meeting.id)}>
              {isProcessing(meeting) ? (
                <ProcessingToggle
                  paused={pausedMeetingIds.includes(meeting.id)}
                  onToggle={(event) => {
                    event.stopPropagation();
                    onToggleProcessing(meeting.id);
                  }}
                  size={16}
                />
              ) : (
                <Box className="state-dot" />
              )}
              <Box sx={{ minWidth: 0 }}>
                <Typography noWrap sx={{ fontWeight: 650 }}>
                  {meeting.title}
                </Typography>
                <Typography color="textSecondary" noWrap>
                  {formatDate(meeting.date)} · {meeting.source}
                  {!isProcessing(meeting) && ` · ${meeting.duration}`}
                </Typography>
              </Box>
              {isProcessing(meeting) && (
                <Box className="processing-status">
                  <ProcessingToggle
                    paused={pausedMeetingIds.includes(meeting.id)}
                    onToggle={(event) => {
                      event.stopPropagation();
                      onToggleProcessing(meeting.id);
                    }}
                    size={14}
                  />
                  <span>
                    {pausedMeetingIds.includes(meeting.id) ? "Paused" : meeting.processingEta}
                  </span>
                </Box>
              )}
            </CardActionArea>
          </Card>
        ))}
        {meetings.length === 0 && (
          <Card className="empty-state">
            <Typography sx={{ fontWeight: 650 }}>No meetings found</Typography>
            <Typography color="textSecondary">Try another filter or upload a recording.</Typography>
          </Card>
        )}
      </Stack>
    </Stack>
  );
}

function ProcessingToggle({ paused, onToggle, size = 16 }) {
  const title = paused ? "Resume processing" : "Pause processing";
  return (
    <Tooltip title={title} arrow>
      <Box
        component="span"
        role="button"
        tabIndex={0}
        className={paused ? "processing-toggle paused" : "processing-toggle"}
        aria-label={title}
        onClick={onToggle}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onToggle(event);
          }
        }}
        style={{ "--spinner-size": `${size}px` }}
      >
        {paused ? (
          <PlayArrowRoundedIcon
            className="processing-toggle-icon resume-icon"
            sx={{ fontSize: size + 4 }}
          />
        ) : (
          <>
            <CircularProgress className="processing-spinner" size={size} thickness={5} />
            <PauseRoundedIcon
              className="processing-toggle-icon pause-icon"
              sx={{ fontSize: size + 4 }}
            />
          </>
        )}
      </Box>
    </Tooltip>
  );
}

function MeetingDetail({
  meeting,
  tab,
  transcriptQuery,
  onTab,
  onTranscriptQuery,
  notes,
  transcript,
  onRevision,
  recordingUrl,
  loading,
  paused,
  onToggleProcessing,
}) {
  const speakers = new Map(
    (transcript?.speakers ?? []).map((item) => [item.id, item.display_name]),
  );
  const segments = (transcript?.segments ?? [])
    .map((item) => ({
      ...item,
      speaker: speakers.get(item.speaker_id) ?? "Unknown speaker",
    }))
    .filter(
      (item) =>
        item.text.toLowerCase().includes(transcriptQuery.toLowerCase()) ||
        item.speaker.toLowerCase().includes(transcriptQuery.toLowerCase()),
    );

  const header = (
    <Stack direction={{ xs: "column", md: "row" }} sx={{ justifyContent: "space-between", gap: 2 }}>
      <Box>
        <Typography variant="h1" sx={{ fontSize: { xs: 34, md: 48 } }}>
          {meeting.title}
        </Typography>
        <Typography className="meeting-date" color="textSecondary">
          {formatDate(meeting.date)}
        </Typography>
      </Box>
      <Stack
        className="meeting-meta-actions"
        direction="row"
        sx={{ gap: 0.75, alignItems: "center" }}
      >
        <ExportControls
          key={`${meeting.id}-${tab}-${transcript?.revision.revision_id}`}
          meetingId={meeting.id}
          tab={tab}
          transcript={transcript}
          notes={notes}
          loading={loading}
        />
        <MetaIcon title={`Source: ${meeting.source}`}>
          {meeting.source === "Google Meet" ? (
            <VideoCameraFrontOutlinedIcon fontSize="small" />
          ) : (
            <CloudUploadOutlinedIcon fontSize="small" />
          )}
        </MetaIcon>
        <MetaIcon title="Workspace access">
          <GroupsOutlinedIcon fontSize="small" />
        </MetaIcon>
      </Stack>
    </Stack>
  );

  return (
    <Stack sx={{ gap: 1.5 }}>
      <Tabs value={tab} onChange={(_, value) => onTab(value)} className="meeting-tabs">
        <Tab value="notes" label="Notes" />
        <Tab value="transcript" label="Transcript" />
        <Tab value="recording" label="Recording" />
      </Tabs>

      {tab === "notes" ? (
        <Card className="notes-panel" sx={{ overflow: "visible" }}>
          {header}
          <Divider sx={{ my: 2.5 }} />
          {isProcessing(meeting) ? (
            <Stack
              className="processing-panel"
              direction="row"
              sx={{ gap: 1.5, alignItems: "center" }}
            >
              <ProcessingToggle paused={paused} onToggle={onToggleProcessing} size={22} />
              <Box>
                <Typography sx={{ fontWeight: 650 }}>
                  {paused ? "Processing paused" : "Processing recording"}
                </Typography>
                <Typography color="textSecondary">
                  {paused
                    ? "Resume when you are ready to continue transcript and notes generation."
                    : `Transcript and notes will appear in ${meeting.processingEta}.`}
                </Typography>
              </Box>
            </Stack>
          ) : meeting.state === "failed" ? (
            <Box className="error-banner" role="alert">
              {meeting.failureReason ?? "Processing failed. Please try another recording."}
            </Box>
          ) : loading ? (
            <Box className="content-loading">
              <CircularProgress size={24} />
            </Box>
          ) : notes ? (
            <Typography component="div" className="notes-text notes-markdown">
              {notes.content}
            </Typography>
          ) : (
            <Typography color="textSecondary">No generated notes are available yet.</Typography>
          )}
        </Card>
      ) : (
        <Box className="recording-grid">
          {tab === "recording" && (
            <Card className="notes-panel">
              {header}
              <Divider sx={{ my: 2.5 }} />
              {recordingUrl ? (
                <Box className="player player-ready">
                  <video controls src={recordingUrl} aria-label={`${meeting.title} recording`} />
                </Box>
              ) : (
                <Box className="player">
                  <Box className="play-circle">
                    <PlayArrowRoundedIcon fontSize="large" />
                  </Box>
                  <Typography sx={{ fontWeight: 650 }}>{meeting.title}</Typography>
                  <Typography>
                    {meeting.recordingAvailable
                      ? "Loading recording..."
                      : "Recording is not available"}
                  </Typography>
                </Box>
              )}
            </Card>
          )}
          <Card className="transcript-panel" sx={{ overflow: "visible" }}>
            {tab === "transcript" && (
              <>
                {header}
                <Divider sx={{ my: 2.5 }} />
              </>
            )}
            <Stack sx={{ gap: 1.5 }}>
              <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center" }}>
                <Typography variant="h2" sx={{ fontSize: 22 }}>
                  {transcript?.revision.revision_type === "original"
                    ? "Original transcript"
                    : transcript
                      ? "Edited transcript"
                      : "Transcript"}
                </Typography>
                <Chip label={transcript?.segments.length ?? 0} size="small" />
              </Stack>
              {transcript?.is_edited && (
                <Button
                  onClick={() =>
                    onRevision(
                      transcript.revision.revision_type === "original"
                        ? null
                        : transcript.original_revision_id,
                    )
                  }
                >
                  {transcript.revision.revision_type === "original"
                    ? "View current transcript"
                    : "View original transcript"}
                </Button>
              )}
              <TextField
                size="small"
                placeholder="Search transcript"
                value={transcriptQuery}
                onChange={(event) => onTranscriptQuery(event.target.value)}
              />
              <Stack sx={{ gap: 1.5 }}>
                {segments.map((item) => (
                  <Box key={item.id} className="transcript-item">
                    <Stack direction="row" sx={{ gap: 1, alignItems: "center" }}>
                      <Box className="speaker-avatar">{item.speaker.slice(-2)}</Box>
                      <Typography sx={{ fontWeight: 650 }}>{item.speaker}</Typography>
                      <Typography color="primary">{formatTimestamp(item.start_seconds)}</Typography>
                    </Stack>
                    <Typography color="textSecondary">{item.text}</Typography>
                  </Box>
                ))}
                {!loading && segments.length === 0 && (
                  <Typography color="textSecondary">
                    {transcript
                      ? "No transcript matches your search."
                      : "Transcript is not available yet."}
                  </Typography>
                )}
              </Stack>
            </Stack>
          </Card>
        </Box>
      )}
    </Stack>
  );
}

export function ExportDownloadMenu({ meetingId, tab, transcript, onDownload }) {
  if (tab === "notes") {
    return (
      <MenuList aria-label="Notes download formats">
        <MenuItem component="a" href={api.notesExportUrl(meetingId)} onClick={onDownload}>
          Markdown (.md)
        </MenuItem>
      </MenuList>
    );
  }
  const version = transcript.revision.revision_type === "original" ? "original" : "current";
  return (
    <MenuList
      aria-label={`${version === "original" ? "Original" : "Current"} transcript download formats`}
    >
      <MenuItem
        component="a"
        href={api.transcriptExportUrl(meetingId, { version, timestamps: false })}
        onClick={onDownload}
      >
        Markdown (.md)
      </MenuItem>
      <MenuItem
        component="a"
        href={api.transcriptExportUrl(meetingId, { version })}
        onClick={onDownload}
      >
        Markdown with timestamps (.md)
      </MenuItem>

      <MenuItem
        component="a"
        href={api.transcriptExportUrl(meetingId, { version, format: "vtt" })}
        onClick={onDownload}
      >
        WebVTT (.vtt)
      </MenuItem>
    </MenuList>
  );
}

export function ExportControls({ meetingId, tab, transcript, notes, loading }) {
  const [open, setOpen] = useState(false);
  const button = useRef(null);
  const menuId = useId();
  if (loading || (tab === "notes" ? !notes : tab !== "transcript" || !transcript)) return null;
  return (
    <Box
      sx={{ position: "relative" }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={(event) => {
        if (!event.currentTarget.contains(document.activeElement)) setOpen(false);
      }}
      onFocus={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(true);
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          setOpen(false);
          button.current?.focus();
        }
      }}
    >
      <IconButton
        ref={button}
        className="meta-icon-button"
        size="small"
        aria-label={tab === "notes" ? "Download notes" : "Download transcript"}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen(true)}
      >
        <DownloadOutlinedIcon fontSize="small" />
      </IconButton>
      {open && (
        <Paper
          id={menuId}
          elevation={3}
          sx={{ position: "absolute", top: "100%", right: 0, zIndex: 10, minWidth: 220 }}
        >
          <ExportDownloadMenu
            meetingId={meetingId}
            tab={tab}
            transcript={transcript}
            onDownload={() => setOpen(false)}
          />
        </Paper>
      )}
    </Box>
  );
}

function MetaIcon({ title, children }) {
  return (
    <Tooltip title={title} arrow>
      <IconButton className="meta-icon-button" size="small" aria-label={title}>
        {children}
      </IconButton>
    </Tooltip>
  );
}

if (!import.meta.env.SSR) {
  createRoot(document.getElementById("root")).render(<App />);
}
