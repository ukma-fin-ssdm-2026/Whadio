import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import { Box, CircularProgress, IconButton, Stack, Tooltip } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { currentUserQuery } from "@/features/accounts/api/current-user";
import { McpKeyPanel } from "@/features/accounts/components/McpKeyPanel";
import { SignInForm } from "@/features/accounts/components/SignInForm";
import { SignOutButton } from "@/features/accounts/components/SignOutButton";
import { ExportMenu } from "@/features/export/components/ExportMenu";
import { isMeetingGone, meetingQueries } from "@/features/meetings/api/meetings";
import { MeetingDetail } from "@/features/meetings/detail/MeetingDetail";
import { AllMeetings } from "@/features/meetings/library/AllMeetings";
import { WorkspaceMeetings } from "@/features/meetings/library/WorkspaceMeetings";
import { MeetingFigures } from "@/features/meetings/MeetingFigures";
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

export function App() {
  const [signedOut, setSignedOut] = useState(false);
  const [signInError, setSignInError] = useState("");

  const endSession = useCallback(() => setSignedOut(true), []);

  // Sign-in leaves the URL alone, so the signed-in app opens the page the user asked for.
  const handleSignedIn = () => {
    setSignInError("");
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
        <SignedInApp onSignedOut={endSession} onLoadFailed={handleLoadFailed} />
      )}
    </AppProviders>
  );
}

function SignedInApp({ onSignedOut, onLoadFailed }) {
  const { data: user, error: userError } = useQuery(currentUserQuery());
  const { data: workspaces, error: workspacesError } = useQuery(workspaceQueries.list());
  const error = (!user && userError) || (!workspaces && workspacesError);

  useEffect(() => {
    // A 401 already ended the session through the query client.
    if (error && error.status !== 401) onLoadFailed(error.message);
  }, [error, onLoadFailed]);

  if (!user || !workspaces) {
    return (
      <Box className="auth-screen">
        <CircularProgress />
      </Box>
    );
  }
  return <Workbench user={user} workspaces={workspaces} onSignedOut={onSignedOut} />;
}

function Workbench({ user, workspaces, onSignedOut }) {
  const [view, setView] = useState("home");
  const [chosenWorkspaceId, setWorkspaceId] = useState("");
  const [meetingId, setMeetingId] = useState("");
  const [meetingLink, setMeetingLink] = useState(() => readMeetingLink(window.location.href));
  const [meetingTab, setMeetingTab] = useState("notes");
  const [transcriptQuery, setTranscriptQuery] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);

  const workspaceId = chosenWorkspaceId || workspaces[0]?.id || "";
  const workspace = workspaces.find((item) => item.id === workspaceId) ?? workspaces[0];
  const opened = useQuery({
    ...meetingQueries.detail(meetingId),
    enabled: view === "meeting" && Boolean(meetingId),
  });
  const selectedMeeting = isMeetingGone(opened.error) ? undefined : opened.data;

  useEffect(() => {
    if (view === "meeting" && selectedMeeting) setWorkspaceId(selectedMeeting.workspaceId);
  }, [view, selectedMeeting]);

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
  }, [meetingLink]);

  const clearMeetingLink = () => {
    window.history.pushState(null, "", meetingLibraryPath(window.location.href));
    setMeetingLink(null);
  };

  const openWorkspace = (id) => {
    clearMeetingLink();
    setWorkspaceId(id);
    setMeetingId("");
    setSettingsOpen(false);
    setView("workspace");
  };

  const openMeeting = (id, revisionId = null, tab = null) => {
    window.history.pushState({ tab }, "", meetingPath(window.location.href, id, revisionId));
    setMeetingLink({ ...readMeetingLink(window.location.href), tab });
  };

  const showMeetings = () => {
    clearMeetingLink();
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

        {view === "meeting" && opened.isError && (
          <Box className="error-banner" role="alert">
            {opened.error.message}
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
        {view === "meeting" && opened.isLoading && (
          <CircularProgress aria-label="Loading meeting" sx={{ alignSelf: "center" }} />
        )}
        {view === "meeting" && selectedMeeting && (
          <MeetingDetail
            meeting={selectedMeeting}
            revisionId={meetingLink?.revisionId ?? null}
            tab={meetingTab}
            transcriptQuery={transcriptQuery}
            onTranscriptQuery={setTranscriptQuery}
            onTab={setMeetingTab}
            onRevision={(revisionId) => openMeeting(selectedMeeting.id, revisionId, "transcript")}
            renderExport={({ transcript, notes }) => (
              <ExportMenu
                meetingId={selectedMeeting.id}
                tab={meetingTab}
                transcript={transcript}
                notes={notes}
              />
            )}
          />
        )}
      </Stack>
    </AppShell>
  );
}
