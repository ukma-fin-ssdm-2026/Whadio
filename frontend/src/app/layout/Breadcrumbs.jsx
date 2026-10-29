import { Box, Stack } from "@mui/material";

export function Breadcrumbs({ view, workspace, meeting, onHome, onWorkspace }) {
  if (view === "home") return <Box className="breadcrumbs" />;
  return (
    <Stack direction="row" className="breadcrumbs" sx={{ alignItems: "center", gap: 1 }}>
      <button type="button" onClick={onHome}>
        Home
      </button>
      <span>/</span>
      {view === "meetings" ? (
        <span>Meetings</span>
      ) : (
        <button type="button" onClick={() => onWorkspace(workspace.id)}>
          {workspace.name}
        </button>
      )}
      {view === "meeting" && meeting && (
        <>
          <span>/</span>
          <span>{meeting.title}</span>
        </>
      )}
    </Stack>
  );
}
