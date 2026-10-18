import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Box,
  Button,
  Card,
  CardActionArea,
  Chip,
  CircularProgress,
  CssBaseline,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  ThemeProvider,
  Tooltip,
  Typography,
  createTheme,
} from "@mui/material";
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import GroupsOutlinedIcon from "@mui/icons-material/GroupsOutlined";
import HomeOutlinedIcon from "@mui/icons-material/HomeOutlined";
import NotesOutlinedIcon from "@mui/icons-material/NotesOutlined";
import PauseRoundedIcon from "@mui/icons-material/PauseRounded";
import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import SearchRoundedIcon from "@mui/icons-material/SearchRounded";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import StopCircleOutlinedIcon from "@mui/icons-material/StopCircleOutlined";
import VideoCameraFrontOutlinedIcon from "@mui/icons-material/VideoCameraFrontOutlined";
import WorkspacesOutlinedIcon from "@mui/icons-material/WorkspacesOutlined";
import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import { ApiError, api } from "./api";
import "./styles.css";

const data = {
  user: {
    name: "Margaret Hamilton",
    email: "margaret@whadio.dev",
  },
  workspaces: [
    {
      id: "team",
      name: "Whadio team",
      role: "Owner",
      members: 3,
      provider: "Whadio",
    },
    {
      id: "personal",
      name: "Margaret Hamilton",
      role: "Owner",
      members: 1,
      provider: "Whadio",
    },
  ],
  meetings: [
    {
      id: "lab3-follow-up",
      workspaceId: "team",
      title: "Lab 3 architecture follow-up",
      date: "2026-09-27T13:30:00",
      state: "queued",
      duration: "Duration pending",
      processingEta: "about 2 min",
      source: "Upload",
    },
    {
      id: "lab3-planning",
      workspaceId: "team",
      title: "Lab 3 architecture planning",
      date: "2026-09-24T19:02:00",
      state: "processed",
      duration: "27m 12s",
      source: "Upload",
    },
    {
      id: "lab2-review",
      workspaceId: "team",
      title: "Lab 2 requirements review",
      date: "2026-09-19T18:40:00",
      state: "processed",
      duration: "40m 10s",
      source: "Upload",
    },
    {
      id: "thesis-consultation",
      workspaceId: "personal",
      title: "Thesis consultation",
      date: "2026-09-25T16:30:00",
      state: "processed",
      duration: "45m 30s",
      source: "Upload",
    },
  ],
  notes: {
    summary:
      "Команда погодила напрям для Lab 3: модульний моноліт із кількома entry points, message broker та окремими ML workers для транскрипції й генерації нотаток. Мікросервіси визнали надмірними для масштабу лабораторної.",
    actions: [
      "Зафіксувати архітектурний стиль як modular monolith з окремими workers.",
      "Підготувати component, deployment та sequence diagrams.",
      "Визначити модель даних: ER або domain model.",
      "Зустрітися в суботу о 13:30 для уточнення ролей і деталей.",
    ],
  },
  transcript: [
    {
      speaker: "Speaker 02",
      time: "02:13",
      text: "Треба обрати архітектурний стиль, створити діаграму компонентів, описати інтерфейси між компонентами і додати діаграму розгортання.",
    },
    {
      speaker: "Speaker 02",
      time: "03:24",
      text: "Мікросервіси виглядають трохи overkill для нашого проєкту. Можливо, треба щось простіше.",
    },
    {
      speaker: "Speaker 02",
      time: "06:29",
      text: "Це може бути модульний моноліт. Для GPU-частини можна мати окремі ML workers для транскрипції і генерації нотаток.",
    },
    {
      speaker: "Speaker 00",
      time: "10:43",
      text: "Це як моноліт, але різні компоненти. Треба мати загальну ідею, а імплементацію можна уточнювати пізніше.",
    },
    {
      speaker: "Speaker 04",
      time: "26:10",
      text: "Пропоную зустрітися в суботу о 13:30 і уточнити розподіл ролей.",
    },
  ],
};

const USER_STORAGE_KEY = "whadio-user";

function titleCase(value) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : "";
}

function formatDuration(seconds) {
  if (seconds == null) return "Duration pending";
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return `${minutes}m ${remaining}s`;
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
    fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
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

function App() {
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
  const [workspacesOpen, setWorkspacesOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState("all");
  const [meetingTab, setMeetingTab] = useState("notes");
  const [transcriptQuery, setTranscriptQuery] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [pausedMeetingIds, setPausedMeetingIds] = useState([]);

  const loadData = useCallback(async () => {
    const workspacePage = await api.listWorkspaces();
    const workspaceDetails = await Promise.all(
      workspacePage.items.map((item) => api.getWorkspace(item.id)),
    );
    const nextWorkspaces = workspacePage.items.map((item, index) =>
      mapWorkspace(item, workspaceDetails[index]),
    );
    const meetingPages = await Promise.all(
      nextWorkspaces.map((item) => api.listMeetings(item.id)),
    );
    setWorkspaces(nextWorkspaces);
    const nextMeetings = meetingPages.flatMap((page) => page.items.map(mapMeeting));
    setMeetings((current) => nextMeetings.map((meeting) => {
      const previous = current.find((item) => item.id === meeting.id);
      return previous?.recordingAvailable
        ? { ...meeting, recordingAvailable: true, failureReason: previous.failureReason }
        : meeting;
    }));
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
    if (authStatus !== "signedIn" || !meetings.some((item) =>
      ["recording", "queued", "processing"].includes(item.state))) return undefined;
    const timer = window.setInterval(() => {
      loadData().catch((caught) => setError(caught.message));
    }, 10000);
    return () => window.clearInterval(timer);
  }, [authStatus, loadData, meetings]);

  const workspace = workspaces.find((item) => item.id === workspaceId) ?? workspaces[0];
  const selectedMeeting = meetings.find((item) => item.id === meetingId);

  const visibleMeetings = useMemo(() => {
    const source = view === "meetings"
      ? meetings
      : meetings.filter((item) => item.workspaceId === workspaceId);

    return source
      .filter((item) => item.title.toLowerCase().includes(query.toLowerCase()))
      .filter((item) => stateFilter === "all"
        || (stateFilter === "queued" ? isProcessing(item) : item.state === stateFilter))
      .sort((left, right) => new Date(right.date) - new Date(left.date));
  }, [meetings, query, stateFilter, view, workspaceId]);

  const loadMeetingContent = useCallback(async (id) => {
    setContentLoading(true);
    setNotes(null);
    setTranscript(null);
    setRecordingUrl("");
    try {
      const detail = await api.getMeeting(id);
      const mapped = mapMeeting(detail);
      setMeetings((items) => items.map((item) => item.id === id ? mapped : item));
      if (detail.processing_state === "processed") {
        const [notesPage, transcriptResult] = await Promise.all([
          api.listNotes(id),
          api.getTranscript(id),
        ]);
        setNotes(notesPage.items[0] ?? null);
        setTranscript(transcriptResult);
      }
    } catch (caught) {
      setError(caught.message);
    } finally {
      setContentLoading(false);
    }
  }, []);

  const openWorkspace = (id) => {
    setWorkspaceId(id);
    setMeetingId("");
    setQuery("");
    setStateFilter("all");
    setWorkspacesOpen(true);
    setSettingsOpen(false);
    setView("workspace");
  };

  const openMeeting = (id) => {
    const meeting = meetings.find((item) => item.id === id);
    if (!meeting) return;
    setWorkspaceId(meeting.workspaceId);
    setMeetingId(id);
    setMeetingTab("notes");
    setTranscriptQuery("");
    setWorkspacesOpen(true);
    setSettingsOpen(false);
    setView("meeting");
    loadMeetingContent(id);
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

  const title = view === "home"
    ? "Workspaces"
    : view === "meetings"
      ? "Meetings"
      : view === "meeting"
        ? selectedMeeting?.title ?? "Meeting"
        : workspace?.name ?? "Workspace";

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
    loadMeetingContent(mapped.id);
  };

  if (authStatus !== "signedIn") {
    return (
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {authStatus === "loading"
          ? <Box className="auth-screen"><CircularProgress /></Box>
          : <SignIn onSubmit={handleSignIn} externalError={error} />}
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
          <Breadcrumbs view={view} workspace={workspace} meeting={selectedMeeting} onHome={() => setView("home")} onWorkspace={openWorkspace} />

          {view !== "meeting" && (
            <Stack direction="row" justifyContent="space-between" alignItems="flex-end" gap={2} className="page-header">
              <Box>
                {view === "workspace" && <Typography className="eyebrow">{workspace.role} workspace</Typography>}
                <Typography variant="h1" fontSize={{ xs: 36, md: 52 }}>{title}</Typography>
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

          {error && <Box className="error-banner" role="alert">{error}</Box>}
          {view === "home" && <HomeView workspaces={workspaces} meetings={meetings} onWorkspace={openWorkspace} />}
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
              onTab={(value) => value === "recording" ? showRecording() : setMeetingTab(value)}
              notes={notes}
              transcript={transcript}
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
          <Typography variant="h1" fontSize={32}>Sign in</Typography>
          <Typography color="text.secondary">Open your meetings, notes, and transcripts.</Typography>
        </Box>
        <TextField label="Email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
        <TextField label="Password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
        {(error || externalError) && <Typography color="error" role="alert">{error || externalError}</Typography>}
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
        <Box minWidth={0}>
          <Typography fontWeight={650} noWrap>{user?.name ?? "Signed in"}</Typography>
          <Typography color="text.secondary" noWrap>{user?.email}</Typography>
        </Box>
        <Tooltip title="Sign out" arrow>
          <IconButton size="small" aria-label="Sign out" onClick={onSignOut} sx={{ ml: "auto" }}>
            <LogoutOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Card>

      <Stack component="nav" gap={0.5}>
        <NavButton active={activeView === "home"} icon={<HomeOutlinedIcon />} onClick={onHome}>Home</NavButton>
        <NavButton active={activeView === "meetings"} icon={<NotesOutlinedIcon />} onClick={onMeetings}>Meetings</NavButton>
        <NavButton active={open} icon={<WorkspacesOutlinedIcon />} onClick={onToggleWorkspaces}>Workspaces</NavButton>

        {open && (
          <Stack gap={0.5} className="workspace-tree">
            {workspaces.map((workspace) => {
              const workspaceMeetings = meetings.filter((item) => item.workspaceId === workspace.id);
              return (
                <Box key={workspace.id}>
                  <Button
                    fullWidth
                    className={workspace.id === workspaceId ? "workspace-node active" : "workspace-node"}
                    onClick={() => onWorkspace(workspace.id)}
                    endIcon={<span className="workspace-count">{workspaceMeetings.length}</span>}
                  >
                    {workspace.name}
                  </Button>
                  <Stack className="transcript-links">
                    {workspaceMeetings.map((meeting) => (
                      <button
                        key={meeting.id}
                        className={meeting.id === selectedMeetingId ? "transcript-link active" : "transcript-link"}
                        type="button"
                        onClick={() => onMeeting(meeting.id)}
                      >
                        <span>{meeting.title}</span>
                        {["recording", "queued", "processing"].includes(meeting.state) && (
                          <small className={pausedMeetingIds.includes(meeting.id) ? "nav-processing paused" : "nav-processing"}>
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
    <Stack direction="row" alignItems="center" gap={1} className="breadcrumbs">
      <button type="button" onClick={onHome}>Home</button>
      <span>/</span>
      {view === "meetings" ? (
        <span>Meetings</span>
      ) : (
        <button type="button" onClick={() => onWorkspace(workspace.id)}>{workspace.name}</button>
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
    <Stack gap={2}>
      <Card className="quiet-panel">
        <Typography variant="h2" fontSize={24}>Choose a workspace</Typography>
        <Typography color="text.secondary">Upload recordings and review processed meetings.</Typography>
      </Card>
      <Stack gap={1.5}>
        {workspaces.map((workspace) => {
          const workspaceMeetings = meetings.filter((item) => item.workspaceId === workspace.id);
          const active = workspaceMeetings.filter((item) => item.state !== "processed").length;
          return (
            <Card key={workspace.id}>
              <CardActionArea className="workspace-card" onClick={() => onWorkspace(workspace.id)}>
                <Box className="workspace-icon">{workspace.name.charAt(0)}</Box>
                <Box minWidth={0}>
                  <Typography fontWeight={650}>{workspace.name}</Typography>
                  <Typography color="text.secondary">{workspace.role} · {workspace.members} members</Typography>
                </Box>
                <Typography color="text.secondary" fontWeight={650}>{workspaceMeetings.length} meetings, {active} active</Typography>
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
      <Stack direction={{ xs: "column", sm: "row" }} gap={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
        <Box>
          <Typography variant="h2" fontSize={18} fontWeight={650}>Upload recording</Typography>
          <Typography color="text.secondary" fontSize={14}>Queue audio or video for processing.</Typography>
        </Box>
        <Button variant="contained" startIcon={<CloudUploadOutlinedIcon />} onClick={() => setOpen(true)}>
          Upload
        </Button>
      </Stack>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Upload recording</DialogTitle>
        <DialogContent>
          <Stack gap={2} pt={0.5}>
            <TextField label="Meeting name" placeholder="Lab 3 architecture planning" value={name} onChange={(event) => setName(event.target.value)} fullWidth />
            <FormControl fullWidth>
              <InputLabel>Note preset</InputLabel>
              <Select label="Note preset" value={workspace.preset} disabled>
                <MenuItem value={workspace.preset}>{titleCase(workspace.preset)} (workspace default)</MenuItem>
              </Select>
            </FormControl>
            <Button className="file-picker-button" component="label" variant="outlined" startIcon={<CloudUploadOutlinedIcon />}>
              {file?.name ?? "Select file"}
              <input hidden type="file" accept="audio/*,video/*" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            </Button>
            {error && <Typography color="error" role="alert">{error}</Typography>}
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
  return (
    <Card className="settings-panel">
      <Box className="settings-nav">
        <Typography className="eyebrow">Settings</Typography>
        <button className="settings-nav-item active" type="button">Provider</button>
        <button className="settings-nav-item" type="button">Access</button>
        <button className="settings-nav-item" type="button">Upload defaults</button>
      </Box>

      <Stack className="settings-options" gap={1.25}>
        <Box>
          <Typography variant="h2" fontSize={24}>Workspace settings</Typography>
          <Typography color="text.secondary">Configure processing defaults for {workspace.name}.</Typography>
        </Box>

        <Card className="settings-option-card">
          <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" gap={2}>
            <Box>
              <Typography fontWeight={650}>Notes provider</Typography>
              <Typography color="text.secondary">Whadio gemma-3-12b-it is used for generated notes.</Typography>
            </Box>
            <Chip label={workspace.provider} variant="outlined" />
          </Stack>
        </Card>

        <Card className="settings-option-card">
          <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" gap={2}>
            <Box>
              <Typography fontWeight={650}>Workspace access</Typography>
              <Typography color="text.secondary">Members of this workspace can open processed meetings.</Typography>
            </Box>
            <Switch defaultChecked color="primary" />
          </Stack>
        </Card>

        <Card className="settings-option-card">
          <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" gap={2}>
            <Box>
              <Typography fontWeight={650}>Default notes preset</Typography>
              <Typography color="text.secondary">New uploads use the workspace notes preset.</Typography>
            </Box>
            <Chip label={titleCase(workspace.preset)} variant="outlined" />
          </Stack>
        </Card>
      </Stack>
    </Card>
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
    <Stack gap={1.5}>
      <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ xs: "stretch", md: "center" }} gap={1.5}>
        <Typography variant="h2" fontSize={22}>{title}</Typography>
        <Stack direction="row" gap={1}>
          <TextField
            size="small"
            placeholder="Filter by name"
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            InputProps={{ startAdornment: <SearchRoundedIcon color="disabled" sx={{ mr: 1 }} /> }}
          />
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel>State</InputLabel>
            <Select label="State" value={stateFilter} onChange={(event) => onStateFilter(event.target.value)}>
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

      <Stack gap={1}>
        {meetings.map((meeting) => (
          <Card key={meeting.id} className={meeting.id === selectedMeetingId ? "meeting-row active" : "meeting-row"}>
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
              <Box minWidth={0}>
                <Typography fontWeight={650} noWrap>{meeting.title}</Typography>
                <Typography color="text.secondary" noWrap>
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
                  <span>{pausedMeetingIds.includes(meeting.id) ? "Paused" : meeting.processingEta}</span>
                </Box>
              )}
            </CardActionArea>
          </Card>
        ))}
        {meetings.length === 0 && (
          <Card className="empty-state">
            <Typography fontWeight={650}>No meetings found</Typography>
            <Typography color="text.secondary">Try another filter or upload a recording.</Typography>
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
          <PlayArrowRoundedIcon className="processing-toggle-icon resume-icon" sx={{ fontSize: size + 4 }} />
        ) : (
          <>
            <CircularProgress className="processing-spinner" size={size} thickness={5} />
            <PauseRoundedIcon className="processing-toggle-icon pause-icon" sx={{ fontSize: size + 4 }} />
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
  recordingUrl,
  loading,
  paused,
  onToggleProcessing,
}) {
  const speakers = new Map((transcript?.speakers ?? []).map((item) => [item.id, item.display_name]));
  const segments = (transcript?.segments ?? [])
    .map((item) => ({
      ...item,
      speaker: speakers.get(item.speaker_id) ?? "Unknown speaker",
    }))
    .filter((item) =>
      item.text.toLowerCase().includes(transcriptQuery.toLowerCase())
      || item.speaker.toLowerCase().includes(transcriptQuery.toLowerCase()),
    );

  return (
    <Stack gap={1.5}>
      <Tabs value={tab} onChange={(_, value) => onTab(value)} className="meeting-tabs">
        <Tab value="notes" label="Notes" />
        <Tab value="recording" label="Recording" />
      </Tabs>

      {tab === "notes" ? (
        <Card className="notes-panel">
          <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" gap={2}>
            <Box>
              <Typography variant="h1" fontSize={{ xs: 34, md: 48 }}>{meeting.title}</Typography>
              <Typography className="meeting-date" color="text.secondary">{formatDate(meeting.date)}</Typography>
            </Box>
            <Stack className="meeting-meta-actions" direction="row" gap={0.75} alignItems="center">
              <MetaIcon title={`Source: ${meeting.source}`}>
                {meeting.source === "Google Meet"
                  ? <VideoCameraFrontOutlinedIcon fontSize="small" />
                  : <CloudUploadOutlinedIcon fontSize="small" />}
              </MetaIcon>
              <MetaIcon title="Workspace access">
                <GroupsOutlinedIcon fontSize="small" />
              </MetaIcon>
            </Stack>
          </Stack>
          <Divider sx={{ my: 2.5 }} />
          {isProcessing(meeting) ? (
            <Stack className="processing-panel" direction="row" gap={1.5} alignItems="center">
              <ProcessingToggle paused={paused} onToggle={onToggleProcessing} size={22} />
              <Box>
                <Typography fontWeight={650}>{paused ? "Processing paused" : "Processing recording"}</Typography>
                <Typography color="text.secondary">
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
            <Box className="content-loading"><CircularProgress size={24} /></Box>
          ) : notes ? (
            <Typography component="div" className="notes-text notes-markdown">{notes.content}</Typography>
          ) : (
            <Typography color="text.secondary">No generated notes are available yet.</Typography>
          )}
        </Card>
      ) : (
        <Box className="recording-grid">
          <Card className="notes-panel">
            {recordingUrl ? (
              <Box className="player player-ready">
                <video controls src={recordingUrl} aria-label={`${meeting.title} recording`} />
              </Box>
            ) : (
              <Box className="player">
                <Box className="play-circle"><PlayArrowRoundedIcon fontSize="large" /></Box>
                <Typography fontWeight={650}>{meeting.title}</Typography>
                <Typography>{meeting.recordingAvailable ? "Loading recording..." : "Recording is not available"}</Typography>
              </Box>
            )}
          </Card>
          <Card className="transcript-panel">
            <Stack gap={1.5}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="h2" fontSize={22}>Transcript</Typography>
                <Chip label={transcript?.segments.length ?? 0} size="small" />
              </Stack>
              <TextField
                size="small"
                placeholder="Search transcript"
                value={transcriptQuery}
                onChange={(event) => onTranscriptQuery(event.target.value)}
              />
              <Stack gap={1.5}>
                {segments.map((item) => (
                  <Box key={item.id} className="transcript-item">
                    <Stack direction="row" gap={1} alignItems="center">
                      <Box className="speaker-avatar">{item.speaker.slice(-2)}</Box>
                      <Typography fontWeight={650}>{item.speaker}</Typography>
                      <Typography color="primary">{formatTimestamp(item.start_seconds)}</Typography>
                    </Stack>
                    <Typography color="text.secondary">{item.text}</Typography>
                  </Box>
                ))}
                {!loading && segments.length === 0 && (
                  <Typography color="text.secondary">
                    {transcript ? "No transcript matches your search." : "Transcript is not available yet."}
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

function MetaIcon({ title, children }) {
  return (
    <Tooltip title={title} arrow>
      <IconButton className="meta-icon-button" size="small" aria-label={title}>
        {children}
      </IconButton>
    </Tooltip>
  );
}

createRoot(document.getElementById("root")).render(<App />);
