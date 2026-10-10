import React, { useMemo, useState } from "react";
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
  const [view, setView] = useState("home");
  const [workspaceId, setWorkspaceId] = useState(data.workspaces[0].id);
  const [meetingId, setMeetingId] = useState("");
  const [workspacesOpen, setWorkspacesOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState("all");
  const [meetingTab, setMeetingTab] = useState("notes");
  const [transcriptQuery, setTranscriptQuery] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [pausedMeetingIds, setPausedMeetingIds] = useState([]);

  const workspace = data.workspaces.find((item) => item.id === workspaceId) ?? data.workspaces[0];
  const selectedMeeting = data.meetings.find((item) => item.id === meetingId);

  const visibleMeetings = useMemo(() => {
    const source = view === "meetings"
      ? data.meetings
      : data.meetings.filter((item) => item.workspaceId === workspaceId);

    return source
      .filter((item) => item.title.toLowerCase().includes(query.toLowerCase()))
      .filter((item) => stateFilter === "all" || item.state === stateFilter)
      .sort((left, right) => new Date(right.date) - new Date(left.date));
  }, [query, stateFilter, view, workspaceId]);

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
    const meeting = data.meetings.find((item) => item.id === id);
    if (!meeting) return;
    setWorkspaceId(meeting.workspaceId);
    setMeetingId(id);
    setMeetingTab("notes");
    setTranscriptQuery("");
    setWorkspacesOpen(true);
    setSettingsOpen(false);
    setView("meeting");
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
        : workspace.name;

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box className="app-shell">
        <Sidebar
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

          {view === "home" && <HomeView onWorkspace={openWorkspace} />}
          {view === "workspace" && settingsOpen && <WorkspaceSettings workspace={workspace} />}
          {view === "workspace" && !settingsOpen && (
            <>
              <UploadPanel />
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
              onTab={setMeetingTab}
              onTranscriptQuery={setTranscriptQuery}
              paused={pausedMeetingIds.includes(selectedMeeting.id)}
              onToggleProcessing={() => toggleProcessing(selectedMeeting.id)}
            />
          )}
        </Box>
      </Box>
    </ThemeProvider>
  );
}

function Sidebar({
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
}) {
  return (
    <Box component="aside" className="sidebar">
      <Typography className="brand">Whadio</Typography>

      <Card className="profile-card">
        <Box className="avatar">MH</Box>
        <Box minWidth={0}>
          <Typography fontWeight={650} noWrap>{data.user.name}</Typography>
          <Typography color="text.secondary" noWrap>{data.user.email}</Typography>
        </Box>
      </Card>

      <Stack component="nav" gap={0.5}>
        <NavButton active={activeView === "home"} icon={<HomeOutlinedIcon />} onClick={onHome}>Home</NavButton>
        <NavButton active={activeView === "meetings"} icon={<NotesOutlinedIcon />} onClick={onMeetings}>Meetings</NavButton>
        <NavButton active={open} icon={<WorkspacesOutlinedIcon />} onClick={onToggleWorkspaces}>Workspaces</NavButton>

        {open && (
          <Stack gap={0.5} className="workspace-tree">
            {data.workspaces.map((workspace) => {
              const meetings = data.meetings.filter((item) => item.workspaceId === workspace.id);
              return (
                <Box key={workspace.id}>
                  <Button
                    fullWidth
                    className={workspace.id === workspaceId ? "workspace-node active" : "workspace-node"}
                    onClick={() => onWorkspace(workspace.id)}
                    endIcon={<span className="workspace-count">{meetings.length}</span>}
                  >
                    {workspace.name}
                  </Button>
                  <Stack className="transcript-links">
                    {meetings.map((meeting) => (
                      <button
                        key={meeting.id}
                        className={meeting.id === selectedMeetingId ? "transcript-link active" : "transcript-link"}
                        type="button"
                        onClick={() => onMeeting(meeting.id)}
                      >
                        <span>{meeting.title}</span>
                        {meeting.state === "queued" && (
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

function HomeView({ onWorkspace }) {
  return (
    <Stack gap={2}>
      <Card className="quiet-panel">
        <Typography variant="h2" fontSize={24}>Choose a workspace</Typography>
        <Typography color="text.secondary">Upload recordings and review processed meetings.</Typography>
      </Card>
      <Stack gap={1.5}>
        {data.workspaces.map((workspace) => {
          const meetings = data.meetings.filter((item) => item.workspaceId === workspace.id);
          const active = meetings.filter((item) => item.state !== "processed").length;
          return (
            <Card key={workspace.id}>
              <CardActionArea className="workspace-card" onClick={() => onWorkspace(workspace.id)}>
                <Box className="workspace-icon">{workspace.name.charAt(0)}</Box>
                <Box minWidth={0}>
                  <Typography fontWeight={650}>{workspace.name}</Typography>
                  <Typography color="text.secondary">{workspace.role} · {workspace.members} members</Typography>
                </Box>
                <Typography color="text.secondary" fontWeight={650}>{meetings.length} meetings, {active} active</Typography>
              </CardActionArea>
            </Card>
          );
        })}
      </Stack>
    </Stack>
  );
}

function UploadPanel() {
  const [open, setOpen] = useState(false);

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
            <TextField label="Meeting name" placeholder="Lab 3 architecture planning" fullWidth />
            <FormControl fullWidth>
              <InputLabel>Note preset</InputLabel>
              <Select label="Note preset" defaultValue="detailed">
                <MenuItem value="summary">Summary</MenuItem>
                <MenuItem value="detailed">Detailed</MenuItem>
                <MenuItem value="interview">Interview</MenuItem>
              </Select>
            </FormControl>
            <Button className="file-picker-button" component="label" variant="outlined" startIcon={<CloudUploadOutlinedIcon />}>
              Select file
              <input hidden type="file" accept="audio/*,video/*" />
            </Button>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={() => setOpen(false)}>Queue processing</Button>
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
              <Typography color="text.secondary">New uploads start with detailed meeting notes.</Typography>
            </Box>
            <Chip label="Detailed" variant="outlined" />
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
              <MenuItem value="failed">Failed</MenuItem>
            </Select>
          </FormControl>
        </Stack>
      </Stack>

      <Stack gap={1}>
        {meetings.map((meeting) => (
          <Card key={meeting.id} className={meeting.id === selectedMeetingId ? "meeting-row active" : "meeting-row"}>
            <CardActionArea className="meeting-row-content" onClick={() => onMeeting(meeting.id)}>
              {meeting.state === "queued" ? (
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
                  {meeting.state !== "queued" && ` · ${meeting.duration}`}
                </Typography>
              </Box>
              {meeting.state === "queued" && (
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

function MeetingDetail({ meeting, workspace, tab, transcriptQuery, onTab, onTranscriptQuery, paused, onToggleProcessing }) {
  const transcript = data.transcript.filter((item) =>
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
          {meeting.state === "queued" ? (
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
          ) : (
            <Stack gap={2}>
              <Typography variant="h2" fontSize={22}>Overview</Typography>
              <Typography className="notes-text">{data.notes.summary}</Typography>
              <Typography variant="h2" fontSize={22}>Action items</Typography>
              <Stack component="ol" className="action-list">
                {data.notes.actions.map((item) => <li key={item}>{item}</li>)}
              </Stack>
            </Stack>
          )}
        </Card>
      ) : (
        <Box className="recording-grid">
          <Card className="notes-panel">
            <Box className="player">
              <Box className="play-circle"><PlayArrowRoundedIcon fontSize="large" /></Box>
              <Typography fontWeight={650}>{meeting.title}</Typography>
              <Typography>{meeting.duration} recording preview</Typography>
            </Box>
          </Card>
          <Card className="transcript-panel">
            <Stack gap={1.5}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="h2" fontSize={22}>Transcript</Typography>
                <Chip label={data.transcript.length} size="small" />
              </Stack>
              <TextField
                size="small"
                placeholder="Search transcript"
                value={transcriptQuery}
                onChange={(event) => onTranscriptQuery(event.target.value)}
              />
              <Stack gap={1.5}>
                {transcript.map((item) => (
                  <Box key={`${item.speaker}-${item.time}`} className="transcript-item">
                    <Stack direction="row" gap={1} alignItems="center">
                      <Box className="speaker-avatar">{item.speaker.slice(-2)}</Box>
                      <Typography fontWeight={650}>{item.speaker}</Typography>
                      <Typography color="primary">{item.time}</Typography>
                    </Stack>
                    <Typography color="text.secondary">{item.text}</Typography>
                  </Box>
                ))}
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
