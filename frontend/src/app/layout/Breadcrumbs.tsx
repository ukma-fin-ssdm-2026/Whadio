import { Link, Breadcrumbs as MuiBreadcrumbs, Typography } from "@mui/material";
import type { Page } from "../navigation/page";

interface BreadcrumbsProps {
  page: Page;
  workspace: { id: string; name: string } | undefined;
  meeting: { title: string } | undefined;
  onHome: () => void;
  onWorkspace: (id: string) => void;
}

export function Breadcrumbs({ page, workspace, meeting, onHome, onWorkspace }: BreadcrumbsProps) {
  if (page === "home") return null;
  const current =
    page === "meetings" ? "Meetings" : page === "meeting" ? meeting?.title : workspace?.name;
  return (
    <MuiBreadcrumbs aria-label="Breadcrumb">
      <Link component="button" variant="body2" underline="hover" onClick={onHome}>
        Home
      </Link>
      {page === "meeting" && workspace && (
        <Link
          component="button"
          variant="body2"
          underline="hover"
          onClick={() => onWorkspace(workspace.id)}
        >
          {workspace.name}
        </Link>
      )}
      <Typography variant="body2" color="textPrimary" aria-current="page">
        {current}
      </Typography>
    </MuiBreadcrumbs>
  );
}
