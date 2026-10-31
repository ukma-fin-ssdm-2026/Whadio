import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import { Box, CircularProgress, IconButton, Stack, Tooltip } from "@mui/material";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "@/api";
import { McpKeyPanel } from "@/features/accounts/components/McpKeyPanel";
import { SignInForm } from "@/features/accounts/components/SignInForm";
import { SignOutButton } from "@/features/accounts/components/SignOutButton";
import { clearSignedInUser, readSignedInUser } from "@/features/accounts/session-storage";
import { ExportControls } from "@/features/export/components/ExportControls";
import { MeetingDetail } from "@/features/meetings/detail/MeetingDetail";
import { MeetingLibrary } from "@/features/meetings/library/MeetingLibrary";
import { mapMeeting, matchesStateFilter } from "@/features/meetings/model";
import { UploadPanel } from "@/features/meetings/upload/UploadPanel";
import { HomeView } from "@/features/workspaces/components/HomeView";
import { WorkspaceSettings } from "@/features/workspaces/components/WorkspaceSettings";
import { mapWorkspace } from "@/features/workspaces/model";
import { PageHeader } from "@/shared/ui/PageHeader";
import { AppShell } from "./layout/AppShell";
import { Breadcrumbs } from "./layout/Breadcrumbs";
import { Sidebar } from "./layout/Sidebar";
import { meetingLibraryPath, meetingPath, readMeetingLink } from "./navigation/meeting-link";
import { AppProviders } from "./providers";
import "@/styles.css";

export function App() {
  const [authStatus, setAuthStatus] = useState("loading");
  const [user, setUser] = useState(readSignedInUser);
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

  const loadSession = useCallback(
    () =>
      loadData().catch((caught) => {
        if (!(caught instanceof ApiError && caught.status === 401)) setError(caught.message);
        setAuthStatus("signedOut");
      }),
    [loadData],
  );

  useEffect(() => {
    loadSession();
  }, [loadSession]);

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
    setSettingsOpen(false);
    setView("workspace");
  };

  const openMeeting = (id, revisionId = null, tab = null) => {
    window.history.pushState({ tab }, "", meetingPath(window.location.href, id, revisionId));
    setMeetingLink({ ...readMeetingLink(window.location.href), tab });
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

  const handleSignedIn = (signedInUser) => {
    setError("");
    setUser(signedInUser);
    setAuthStatus("loading");
    loadSession();
  };

  const endSession = useCallback(() => {
    requestedMeetingId.current = "";
    clearSignedInUser();
    setUser(null);
    setWorkspaces([]);
    setMeetings([]);
    setAuthStatus("signedOut");
  }, []);

  const handleUpload = async (payload) => {
    const created = await api.uploadMeeting(workspaceId, payload);
    const mapped = mapMeeting(created);
    setMeetings((items) => [mapped, ...items]);
    setMeetingId(mapped.id);
    setMeetingTab("notes");
    setTranscriptQuery("");
    setSettingsOpen(false);
    setView("meeting");
    openMeeting(mapped.id);
  };

  if (authStatus !== "signedIn") {
    return (
      <AppProviders onUnauthorized={endSession}>
        {authStatus === "loading" ? (
          <Box className="auth-screen">
            <CircularProgress />
          </Box>
        ) : (
          <SignInForm onSignedIn={handleSignedIn} externalError={error} />
        )}
      </AppProviders>
    );
  }

  return (
    <AppProviders onUnauthorized={endSession}>
      <AppShell
        renderSidebar={(onNavigate) => (
          <Sidebar
            user={user}
            workspaces={workspaces}
            page={view}
            workspaceId={workspaceId}
            onHome={() => {
              clearMeetingLink();
              setSettingsOpen(false);
              setView("home");
            }}
            onMeetings={showMeetings}
            onWorkspace={openWorkspace}
            signOutAction={<SignOutButton onSignedOut={endSession} />}
            onNavigate={onNavigate}
          />
        )}
      >
        <Stack sx={{ gap: 2 }}>
          <Breadcrumbs
            page={view}
            workspace={workspace}
            meeting={selectedMeeting}
            onHome={() => {
              clearMeetingLink();
              setView("home");
            }}
            onWorkspace={openWorkspace}
          />

          {view !== "meeting" && (
            <PageHeader
              title={title}
              overline={view === "workspace" ? `${workspace.role} workspace` : undefined}
              actions={
                view === "workspace" && (
                  <Tooltip title="Workspace settings" arrow>
                    <IconButton
                      aria-label="Workspace settings"
                      aria-pressed={settingsOpen}
                      color={settingsOpen ? "primary" : "default"}
                      onClick={() => setSettingsOpen((value) => !value)}
                    >
                      <SettingsOutlinedIcon />
                    </IconButton>
                  </Tooltip>
                )
              }
            />
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
            <WorkspaceSettings workspace={workspace} assistantSettings={<McpKeyPanel />} />
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
        </Stack>
      </AppShell>
    </AppProviders>
  );
}
