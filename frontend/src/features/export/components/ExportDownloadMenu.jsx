import { MenuItem, MenuList } from "@mui/material";
import { api } from "@/api";

export function ExportDownloadMenu({ meetingId, tab, transcript, onDownload }) {
  if (tab === "notes") {
    return (
      <MenuList aria-label="Notes download formats">
        <MenuItem component="a" href={api.notesExportUrl(meetingId)} onClick={onDownload}>
          Markdown (.md)
        </MenuItem>
      </MenuList>
    );
  }
  const version = transcript.revision.revision_type === "original" ? "original" : "current";
  return (
    <MenuList
      aria-label={`${version === "original" ? "Original" : "Current"} transcript download formats`}
    >
      <MenuItem
        component="a"
        href={api.transcriptExportUrl(meetingId, { version, timestamps: false })}
        onClick={onDownload}
      >
        Markdown (.md)
      </MenuItem>
      <MenuItem
        component="a"
        href={api.transcriptExportUrl(meetingId, { version })}
        onClick={onDownload}
      >
        Markdown with timestamps (.md)
      </MenuItem>

      <MenuItem
        component="a"
        href={api.transcriptExportUrl(meetingId, { version, format: "vtt" })}
        onClick={onDownload}
      >
        WebVTT (.vtt)
      </MenuItem>
    </MenuList>
  );
}
