import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import { IconButton, Menu, MenuItem } from "@mui/material";
import { useId, useState } from "react";
import type { NoteRead, TranscriptRead } from "@/shared/api/types";
import { notesExportUrl, transcriptExportUrl } from "../api/export-urls";

interface ExportChoices {
  buttonLabel: string;
  listLabel: string;
  links: { label: string; href: string }[];
}

interface ExportMenuProps {
  meetingId: string;
  tab: "notes" | "transcript" | "recording";
  transcript: Pick<TranscriptRead, "revision"> | null;
  notes: NoteRead | null;
}

function notesChoices(meetingId: string): ExportChoices {
  return {
    buttonLabel: "Download notes",
    listLabel: "Notes download formats",
    links: [{ label: "Markdown (.md)", href: notesExportUrl(meetingId) }],
  };
}

function transcriptChoices(
  meetingId: string,
  { revision }: Pick<TranscriptRead, "revision">,
): ExportChoices {
  const version = revision.revision_type === "original" ? "original" : "current";
  return {
    buttonLabel: "Download transcript",
    listLabel: `${version === "original" ? "Original" : "Current"} transcript download formats`,
    links: [
      {
        label: "Markdown (.md)",
        href: transcriptExportUrl(meetingId, { version, timestamps: false }),
      },
      {
        label: "Markdown with timestamps (.md)",
        href: transcriptExportUrl(meetingId, { version }),
      },
      { label: "WebVTT (.vtt)", href: transcriptExportUrl(meetingId, { version, format: "vtt" }) },
    ],
  };
}

function choicesFor({ meetingId, tab, transcript, notes }: ExportMenuProps): ExportChoices | null {
  if (tab === "notes") return notes && notesChoices(meetingId);
  if (tab === "transcript") return transcript && transcriptChoices(meetingId, transcript);
  return null;
}

export function ExportMenu(props: ExportMenuProps) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const menuId = useId();
  const choices = choicesFor(props);
  if (!choices) return null;

  const close = () => setAnchor(null);
  const open = Boolean(anchor);
  return (
    <>
      <IconButton
        className="meta-icon-button"
        size="small"
        aria-label={choices.buttonLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={(event) => setAnchor(event.currentTarget)}
      >
        <DownloadOutlinedIcon fontSize="small" />
      </IconButton>
      <Menu
        id={menuId}
        anchorEl={anchor}
        open={open}
        onClose={close}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
        slotProps={{ list: { "aria-label": choices.listLabel } }}
      >
        {choices.links.map(({ label, href }) => (
          <MenuItem key={href} component="a" href={href} onClick={close}>
            {label}
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}
