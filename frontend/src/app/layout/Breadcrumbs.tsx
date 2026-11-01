import { Breadcrumbs as MuiBreadcrumbs, Typography } from "@mui/material";
import { TextLink } from "../navigation/links";

interface BreadcrumbsProps {
  workspace?: { id: string; name: string } | undefined;
  current: string;
}

export function Breadcrumbs({ workspace, current }: BreadcrumbsProps) {
  return (
    <MuiBreadcrumbs aria-label="Breadcrumb">
      <TextLink to="/">Home</TextLink>
      {workspace && (
        <TextLink to="/workspaces/$workspaceId" params={{ workspaceId: workspace.id }}>
          {workspace.name}
        </TextLink>
      )}
      <Typography variant="body2" color="textPrimary" aria-current="page">
        {current}
      </Typography>
    </MuiBreadcrumbs>
  );
}
