import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import { IconButton, Tooltip } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Outlet, useMatchRoute } from "@tanstack/react-router";
import { Breadcrumbs } from "@/app/layout/Breadcrumbs";
import { NotFoundMessage } from "@/app/layout/NotFoundPage";
import { workspaceQueries } from "@/features/workspaces/api/workspaces";
import { PageHeader } from "@/shared/ui/PageHeader";

export const Route = createFileRoute("/_authed/workspaces/$workspaceId")({
  component: WorkspaceRoute,
});

function WorkspaceRoute() {
  const navigate = Route.useNavigate();
  const { workspaceId } = Route.useParams();
  const matchRoute = useMatchRoute();
  const { data: workspaces = [] } = useQuery(workspaceQueries.list());
  const workspace = workspaces.find((item) => item.id === workspaceId);
  if (!workspace) return <NotFoundMessage />;

  const settingsOpen =
    matchRoute({ to: "/workspaces/$workspaceId/settings", params: { workspaceId } }) !== false;

  return (
    <>
      <Breadcrumbs current={workspace.name} />
      <PageHeader
        title={workspace.name}
        overline={`${workspace.role} workspace`}
        actions={
          <Tooltip title="Workspace settings" arrow>
            <IconButton
              aria-label="Workspace settings"
              aria-pressed={settingsOpen}
              color={settingsOpen ? "primary" : "default"}
              onClick={() =>
                navigate({
                  to: settingsOpen
                    ? "/workspaces/$workspaceId"
                    : "/workspaces/$workspaceId/settings",
                  params: { workspaceId },
                })
              }
            >
              <SettingsOutlinedIcon />
            </IconButton>
          </Tooltip>
        }
      />
      <Outlet />
    </>
  );
}
