import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import { Box, IconButton, Paper } from "@mui/material";
import { useId, useRef, useState } from "react";
import { ExportDownloadMenu } from "./ExportDownloadMenu";

export function ExportControls({ meetingId, tab, transcript, notes }) {
  const [open, setOpen] = useState(false);
  const button = useRef(null);
  const menuId = useId();
  if (tab === "notes" ? !notes : tab !== "transcript" || !transcript) return null;
  return (
    <Box
      sx={{ position: "relative" }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={(event) => {
        if (!event.currentTarget.contains(document.activeElement)) setOpen(false);
      }}
      onFocus={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(true);
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          setOpen(false);
          button.current?.focus();
        }
      }}
    >
      <IconButton
        ref={button}
        className="meta-icon-button"
        size="small"
        aria-label={tab === "notes" ? "Download notes" : "Download transcript"}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen(true)}
      >
        <DownloadOutlinedIcon fontSize="small" />
      </IconButton>
      {open && (
        <Paper
          id={menuId}
          elevation={3}
          sx={{ position: "absolute", top: "100%", right: 0, zIndex: 10, minWidth: 220 }}
        >
          <ExportDownloadMenu
            meetingId={meetingId}
            tab={tab}
            transcript={transcript}
            onDownload={() => setOpen(false)}
          />
        </Paper>
      )}
    </Box>
  );
}
