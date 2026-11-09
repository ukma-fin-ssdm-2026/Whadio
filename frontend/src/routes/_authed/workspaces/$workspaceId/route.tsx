import PeopleAltOutlinedIcon from "@mui/icons-material/PeopleAltOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import { IconButton, Tooltip } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Outlet, useMatchRoute } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { Breadcrumbs } from "@/app/layout/Breadcrumbs";
import { NotFoundMessage } from "@/app/layout/NotFoundPage";
import { workspaceQueries } from "@/features/workspaces/api/workspaces";
import { titleCase } from "@/shared/lib/format";
import { PageHeader } from "@/shared/ui/PageHeader";

export const Route = createFileRoute("/_authed/workspaces/$workspaceId")({
  component: WorkspaceRoute,
});

interface WorkspacePageButtonProps {
  workspaceId: string;
  to: "/workspaces/$workspaceId/members" | "/workspaces/$workspaceId/settings";
  label: string;
  icon: ReactNode;
}

function WorkspacePageButton({ workspaceId, to, label, icon }: WorkspacePageButtonProps) {
  const navigate = Route.useNavigate();
  const matchRoute = useMatchRoute();
  const open = matchRoute({ to, params: { workspaceId } }) !== false;

  return (
    <Tooltip title={label} arrow>
      <IconButton
        aria-label={label}
        aria-pressed={open}
        color={open ? "primary" : "default"}
        onClick={() =>
          navigate({ to: open ? "/workspaces/$workspaceId" : to, params: { workspaceId } })
        }
      >
        {icon}
      </IconButton>
    </Tooltip>
  );
}

function WorkspaceRoute() {
  const { workspaceId } = Route.useParams();
  const { data: workspaces = [] } = useQuery(workspaceQueries.list());
  const workspace = workspaces.find((item) => item.id === workspaceId);
  if (!workspace) return <NotFoundMessage />;

  return (
    <>
      <Breadcrumbs current={workspace.name} />
      <PageHeader
        title={workspace.name}
        overline={`${titleCase(workspace.role)} workspace`}
        actions={
          <>
            {!workspace.personal && (
              <WorkspacePageButton
                workspaceId={workspaceId}
                to="/workspaces/$workspaceId/members"
                label="Workspace members"
                icon={<PeopleAltOutlinedIcon />}
              />
            )}
            <WorkspacePageButton
              workspaceId={workspaceId}
              to="/workspaces/$workspaceId/settings"
              label="Workspace settings"
              icon={<SettingsOutlinedIcon />}
            />
          </>
        }
      />
      <Outlet />
    </>
  );
}
