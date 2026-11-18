import AutorenewOutlinedIcon from "@mui/icons-material/AutorenewOutlined";
import { Alert, Box, Button, Card, CircularProgress, Stack, Typography } from "@mui/material";
import { type ReactNode, useState } from "react";
import type { NoteRead } from "@/shared/api/types";
import { formatDate, titleCase } from "@/shared/lib/format";
import { ErrorBanner } from "@/shared/ui/ErrorBanner";
import { Markdown } from "@/shared/ui/Markdown";
import { describeFailure, IN_PROGRESS_LABELS, isInProgress, type Meeting } from "../model";
import { NoteVersionsMenu } from "./NoteVersionsMenu";
import { type PresetFieldProps, RegenerateNotesDialog } from "./RegenerateNotesDialog";

interface NotesPanelProps {
  meeting: Meeting;
  notes: NoteRead | null;
  hasEarlierNotes: boolean;
  loading: boolean;
  failed: boolean;
  canRegenerate: boolean;
  renderPresetField: (field: PresetFieldProps) => ReactNode;
}

interface NotesContentProps {
  meeting: Meeting;
  notes: NoteRead | null;
  shown: NoteRead | null;
  loading: boolean;
}

function Progress({ children }: { children: ReactNode }) {
  return (
    <Stack
      direction="row"
      sx={{
        gap: 1.5,
        alignItems: "center",
        p: "1rem",
        borderRadius: "0.5rem",
        bgcolor: "background.subtle",
      }}
    >
      <CircularProgress size={22} thickness={5} />
      <Box>{children}</Box>
    </Stack>
  );
}

function NotesContent({ meeting, notes, shown, loading }: NotesContentProps) {
  if (isInProgress(meeting.state) && !shown) {
    return (
      <Progress>
        <Typography variant="subtitle1">{IN_PROGRESS_LABELS[meeting.state]}</Typography>
        <Typography color="textSecondary">
          Notes appear here when processing finishes. The transcript appears in its tab as soon as
          it is ready.
        </Typography>
      </Progress>
    );
  }
  if (isInProgress(meeting.state) && shown) {
    return (
      <>
        <Progress>
          <Typography role="status" color="textSecondary">
            Regenerating notes. The current notes stay until the new ones are ready.
          </Typography>
        </Progress>
        <Markdown>{shown.content}</Markdown>
      </>
    );
  }
  if (meeting.state === "failed") {
    return (
      <>
        <ErrorBanner>
          {describeFailure(meeting.failureReason)}
          {notes && " The previous notes are still current."}
        </ErrorBanner>
        {shown && <Markdown>{shown.content}</Markdown>}
      </>
    );
  }
  if (loading) {
    return (
      <Box sx={{ display: "grid", minHeight: "8rem", placeItems: "center" }}>
        <CircularProgress size={24} />
      </Box>
    );
  }
  if (!shown) {
    return <Typography color="textSecondary">No generated notes are available yet.</Typography>;
  }
  return <Markdown>{shown.content}</Markdown>;
}

export function NotesPanel({
  meeting,
  notes,
  hasEarlierNotes,
  loading,
  failed,
  canRegenerate,
  renderPresetField,
}: NotesPanelProps) {
  const [shownVersion, setShownVersion] = useState<NoteRead | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  if (failed && !notes && meeting.state === "processed") return null;
  const shown = shownVersion ?? notes;
  return (
    <Card sx={{ p: { xs: 2, md: 3 } }}>
      <Stack sx={{ gap: 1.5 }}>
        <Stack
          direction="row"
          sx={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 1 }}
        >
          <Box>
            <Typography variant="h2">{shownVersion ? "Earlier notes" : "Notes"}</Typography>
            {shown && (
              <Typography color="textSecondary">
                {titleCase(shown.preset)} preset · {formatDate(shown.created_at)}
              </Typography>
            )}
          </Box>
          <Stack direction="row" sx={{ gap: 1, alignItems: "center", ml: "auto" }}>
            {canRegenerate && (
              <Button startIcon={<AutorenewOutlinedIcon />} onClick={() => setDialogOpen(true)}>
                Regenerate notes
              </Button>
            )}
            {(hasEarlierNotes || shownVersion) && (
              <NoteVersionsMenu
                meetingId={meeting.id}
                shownId={shown?.id ?? null}
                onShow={setShownVersion}
              />
            )}
          </Stack>
        </Stack>
        {shownVersion && (
          <Alert
            severity="info"
            role="status"
            action={
              <Button color="inherit" size="small" onClick={() => setShownVersion(null)}>
                View current notes
              </Button>
            }
          >
            Newer notes have replaced these.
          </Alert>
        )}
        <NotesContent meeting={meeting} notes={notes} shown={shown} loading={loading} />
      </Stack>
      {/* Not gated on canRegenerate: a refusal as already running must outlive the reload. */}
      {dialogOpen && (
        <RegenerateNotesDialog
          meeting={meeting}
          renderPresetField={renderPresetField}
          onClose={() => setDialogOpen(false)}
        />
      )}
    </Card>
  );
}
