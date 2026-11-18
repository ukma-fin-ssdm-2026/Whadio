import HistoryOutlinedIcon from "@mui/icons-material/HistoryOutlined";
import { Alert, Box, Button, Menu, MenuItem } from "@mui/material";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import type { NoteRead } from "@/shared/api/types";
import { formatDate, titleCase } from "@/shared/lib/format";
import { meetingQueries } from "../api/meetings";

interface NoteVersionsMenuProps {
  meetingId: string;
  shownId: string | null;
  onShow: (note: NoteRead | null) => void;
}

const versionLabel = (note: NoteRead) =>
  `${titleCase(note.preset)} · ${formatDate(note.created_at)}${note.is_current ? " (current)" : ""}`;

export function NoteVersionsMenu({ meetingId, shownId, onShow }: NoteVersionsMenuProps) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const menuId = useId();
  const open = Boolean(anchor);
  const versions = useInfiniteQuery({ ...meetingQueries.noteVersions(meetingId), enabled: open });

  const close = () => setAnchor(null);
  const show = (note: NoteRead) => {
    onShow(note.is_current ? null : note);
    close();
  };

  return (
    <>
      <Button
        startIcon={<HistoryOutlinedIcon />}
        aria-label="Notes versions"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={(event) => setAnchor(event.currentTarget)}
      >
        Versions
      </Button>
      <Menu
        id={menuId}
        anchorEl={anchor}
        open={open}
        onClose={close}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
        slotProps={{ list: { "aria-label": "Notes versions" } }}
      >
        {versions.isPending && <MenuItem disabled>Loading notes versions</MenuItem>}
        {versions.isError && (
          <Box component="li" role="none" sx={{ px: 1.5, py: 0.5 }}>
            <Alert severity="error">{versions.error.message}</Alert>
          </Box>
        )}
        {versions.data?.map((note) => (
          <MenuItem key={note.id} selected={note.id === shownId} onClick={() => show(note)}>
            {versionLabel(note)}
          </MenuItem>
        ))}
        {versions.hasNextPage && (
          <MenuItem
            disabled={versions.isFetchingNextPage}
            onClick={() => void versions.fetchNextPage()}
          >
            {versions.isFetchingNextPage ? "Loading more versions" : "Load more versions"}
          </MenuItem>
        )}
      </Menu>
    </>
  );
}
