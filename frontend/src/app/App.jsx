import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import { Box, CircularProgress, IconButton, Stack, Tooltip } from "@mui/material";
import { queryOptions, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api";
import { McpKeyPanel } from "@/features/accounts/components/McpKeyPanel";
import { SignInForm } from "@/features/accounts/components/SignInForm";
import { SignOutButton } from "@/features/accounts/components/SignOutButton";
import { clearSignedInUser, readSignedInUser } from "@/features/accounts/session-storage";
import { ExportControls } from "@/features/export/components/ExportControls";
import { pollWhileInProgress } from "@/features/meetings/api/meetings";
import { MeetingDetail } from "@/features/meetings/detail/MeetingDetail";
import { AllMeetings } from "@/features/meetings/library/AllMeetings";
import { WorkspaceMeetings } from "@/features/meetings/library/WorkspaceMeetings";
import { MeetingFigures } from "@/features/meetings/MeetingFigures";
import { mapMeeting } from "@/features/meetings/model";
import { UploadPanel } from "@/features/meetings/upload/UploadPanel";
import { workspaceQueries } from "@/features/workspaces/api/workspaces";
import { HomeView } from "@/features/workspaces/components/HomeView";
import { WorkspacePresetField } from "@/features/workspaces/components/WorkspacePresetField";
import { WorkspaceSettings } from "@/features/workspaces/components/WorkspaceSettings";
import { PageHeader } from "@/shared/ui/PageHeader";
import { AppShell } from "./layout/AppShell";
import { Breadcrumbs } from "./layout/Breadcrumbs";
import { Sidebar } from "./layout/Sidebar";
import { meetingLibraryPath, meetingPath, readMeetingLink } from "./navigation/meeting-link";
import { AppProviders } from "./providers";
import "@/styles.css";

const openedMeetingQuery = (id) =>
  queryOptions({
    queryKey: ["meetings", "detail", id],
    queryFn: () => api.getMeeting(id),
    refetchInterval: ({ state }) => pollWhileInProgress(state.data ? [state.data] : []),
  });

export function App() {
  const [signedOut, setSignedOut] = useState(false);
  const [user, setUser] = useState(readSignedInUser);
  const [signInError, setSignInError] = useState("");

  const endSession = useCallback(() => {
    clearSignedInUser();
    setUser(null);
    setSignedOut(true);
  }, []);

  const handleSignedIn = (signedInUser) => {
    setSignInError("");
    setUser(signedInUser);
    setSignedOut(false);
  };

  const handleLoadFailed = useCallback((message) => {
    setSignInError(message);
    setSignedOut(true);
  }, []);

  return (
    <AppProviders onUnauthorized={endSession}>
      {signedOut ? (
        <SignInForm onSignedIn={handleSignedIn} externalError={signInError} />
      ) : (
        <SignedInApp user={user} onSignedOut={endSession} onLoadFailed={handleLoadFailed} />
      )}
    </AppProviders>
  );
}

function SignedInApp({ user, onSignedOut, onLoadFailed }) {
  const { data: workspaces, error } = useQuery(workspaceQueries.list());

  useEffect(() => {
    // A 401 already ended the session through the query client.
    if (!workspaces && error && error.status !== 401) onLoadFailed(error.message);
  }, [workspaces, error, onLoadFailed]);

  if (!workspaces) {
    return (
      <Box className="auth-screen">
        <CircularProgress />
      </Box>
    );
  }
  return <Workbench user={user} workspaces={workspaces} onSignedOut={onSignedOut} />;
}

function Workbench({ user, workspaces, onSignedOut }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState("");
  const [contentLoading, setContentLoading] = useState(false);
  const [notes, setNotes] = useState(null);
  const [transcript, setTranscript] = useState(null);
  const [recordingUrl, setRecordingUrl] = useState("");
  const [view, setView] = useState("home");
  const [chosenWorkspaceId, setWorkspaceId] = useState("");
  const [meetingId, setMeetingId] = useState("");
  const [meetingLink, setMeetingLink] = useState(() => readMeetingLink(window.location.href));
  const [meetingTab, setMeetingTab] = useState("notes");
  const [transcriptQuery, setTranscriptQuery] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const requestedMeetingId = useRef("");

  const workspaceId = chosenWorkspaceId || workspaces[0]?.id || "";
  const workspace = workspaces.find((item) => item.id === workspaceId) ?? workspaces[0];
  const { data: openedMeeting } = useQuery({
    ...openedMeetingQuery(meetingId),
    enabled: view === "meeting" && Boolean(meetingId),
  });
  const selectedMeeting = openedMeeting && mapMeeting(openedMeeting);

  const loadMeetingContent = useCallback(
    async (id, revisionId = null) => {
      const request = {};
      requestedMeetingId.current = request;
      setContentLoading(true);
      setError("");
      setNotes(null);
      setTranscript(null);
      setRecordingUrl("");
      try {
        const detail = await queryClient.fetchQuery(openedMeetingQuery(id));
        if (requestedMeetingId.current !== request) return;
        setWorkspaceId(detail.workspace_id);
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
        if (requestedMeetingId.current === request) setError(caught.message);
      } finally {
        if (requestedMeetingId.current === request) setContentLoading(false);
      }
    },
    [queryClient],
  );

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
    if (!meetingLink) return;
    setMeetingId(meetingLink.meetingId);
    setMeetingTab(meetingLink.tab ?? (meetingLink.revisionId ? "transcript" : "notes"));
    setTranscriptQuery("");
    setSettingsOpen(false);
    setView("meeting");
    loadMeetingContent(meetingLink.meetingId, meetingLink.revisionId);
    return () => {
      requestedMeetingId.current = "";
    };
  }, [meetingLink, loadMeetingContent]);

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

  return (
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
          signOutAction={<SignOutButton onSignedOut={onSignedOut} />}
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
          <HomeView
            workspaces={workspaces}
            renderMeetingFigures={(id) => <MeetingFigures workspaceId={id} />}
            onWorkspace={openWorkspace}
          />
        )}
        {view === "workspace" && settingsOpen && (
          <WorkspaceSettings workspaceId={workspace.id} assistantSettings={<McpKeyPanel />} />
        )}
        {view === "workspace" && !settingsOpen && (
          <>
            <UploadPanel
              workspaceId={workspace.id}
              presetField={<WorkspacePresetField workspaceId={workspace.id} />}
              onUploaded={openMeeting}
            />
            <WorkspaceMeetings
              key={workspace.id}
              workspaceId={workspace.id}
              selectedMeetingId={meetingId}
              onMeeting={openMeeting}
            />
          </>
        )}
        {view === "meetings" && (
          <AllMeetings
            workspaceIds={workspaces.map((item) => item.id)}
            selectedMeetingId={meetingId}
            onMeeting={openMeeting}
          />
        )}
        {view === "meeting" && !selectedMeeting && contentLoading && (
          <CircularProgress aria-label="Loading meeting" sx={{ alignSelf: "center" }} />
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
  );
}
