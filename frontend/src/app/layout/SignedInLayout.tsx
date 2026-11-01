import { Stack } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { Outlet, useNavigate } from "@tanstack/react-router";
import { sessionQueries } from "@/features/accounts/api/session";
import { SignOutButton } from "@/features/accounts/components/SignOutButton";
import { workspaceQueries } from "@/features/workspaces/api/workspaces";
import { LastMeetingProvider } from "../navigation/LastMeeting";
import { AppShell } from "./AppShell";
import { LoadingScreen } from "./CenteredScreen";
import { RouteError } from "./RouteError";
import { Sidebar } from "./Sidebar";

export function SignedInLayout() {
  const navigate = useNavigate();
  const { data: user } = useQuery(sessionQueries.me());
  const { data: workspaces, error } = useQuery(workspaceQueries.list());

  if (!workspaces) {
    // A 401 already ended the session through the query client.
    return error && error.status !== 401 ? <RouteError error={error} /> : <LoadingScreen />;
  }
  return (
    <LastMeetingProvider>
      <AppShell
        renderSidebar={(onNavigate) => (
          <Sidebar
            user={user ?? null}
            workspaces={workspaces}
            signOutAction={<SignOutButton onSignedOut={() => navigate({ to: "/sign-in" })} />}
            onNavigate={onNavigate}
          />
        )}
      >
        <Stack sx={{ gap: 2 }}>
          <Outlet />
        </Stack>
      </AppShell>
    </LastMeetingProvider>
  );
}
