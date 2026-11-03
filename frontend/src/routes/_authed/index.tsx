import { useQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { MeetingFigures } from "@/features/meetings/MeetingFigures";
import { workspaceQueries } from "@/features/workspaces/api/workspaces";
import { CreateWorkspaceDialog } from "@/features/workspaces/components/CreateWorkspaceDialog";
import { HomeView } from "@/features/workspaces/components/HomeView";
import { PageHeader } from "@/shared/ui/PageHeader";

export const Route = createFileRoute("/_authed/")({ component: HomeRoute });

function HomeRoute() {
  const navigate = useNavigate();
  const { data: workspaces = [] } = useQuery(workspaceQueries.list());
  const openWorkspace = (workspaceId: string) =>
    navigate({ to: "/workspaces/$workspaceId", params: { workspaceId } });
  return (
    <>
      <PageHeader title="Workspaces" />
      <HomeView
        workspaces={workspaces}
        renderMeetingFigures={(id) => <MeetingFigures workspaceId={id} />}
        actions={<CreateWorkspaceDialog onCreated={openWorkspace} />}
        onWorkspace={openWorkspace}
      />
    </>
  );
}
