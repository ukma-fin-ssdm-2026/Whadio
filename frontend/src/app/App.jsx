import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import {
  Box,
  CircularProgress,
  CssBaseline,
  IconButton,
  Stack,
  ThemeProvider,
  Tooltip,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "@/api";
import { McpKeySettings } from "@/features/accounts/components/McpKeySettings";
import { SignIn } from "@/features/accounts/components/SignIn";
import { ExportControls } from "@/features/export/components/ExportControls";
import { MeetingDetail } from "@/features/meetings/detail/MeetingDetail";
import { MeetingLibrary } from "@/features/meetings/library/MeetingLibrary";
import { mapMeeting, matchesStateFilter } from "@/features/meetings/model";
import { UploadPanel } from "@/features/meetings/upload/UploadPanel";
import { HomeView } from "@/features/workspaces/components/HomeView";
import { WorkspaceSettings } from "@/features/workspaces/components/WorkspaceSettings";
import { mapWorkspace } from "@/features/workspaces/model";
import { Breadcrumbs } from "./layout/Breadcrumbs";
import { Sidebar } from "./layout/Sidebar";
import { meetingLibraryPath, meetingPath, readMeetingLink } from "./navigation/meeting-link";
import { theme } from "./theme";
import "@/styles.css";

const USER_STORAGE_KEY = "whadio-user";

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
      .filter((item) => matchesStateFilter(item, stateFilter))
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
          {view === "workspace" && settingsOpen && (
            <WorkspaceSettings workspace={workspace} assistantSettings={<McpKeySettings />} />
          )}
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
              exportControls={
                <ExportControls
                  meetingId={selectedMeeting.id}
                  tab={meetingTab}
                  transcript={transcript}
                  notes={notes}
                  loading={contentLoading}
                />
              }
            />
          )}
        </Box>
      </Box>
    </ThemeProvider>
  );
}
