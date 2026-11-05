import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import { Button, Card, Chip, Stack, TextField, Typography } from "@mui/material";
import { useState } from "react";
import type { TranscriptRead } from "@/shared/api/types";
import { isInProgress, type Meeting } from "../model";
import { SegmentRow } from "./SegmentRow";
import { matchingSegments, NO_MATCH } from "./segments";
import { TranscriptEditor } from "./TranscriptEditor";

interface TranscriptPanelProps {
  meeting: Pick<Meeting, "id" | "state">;
  transcript: TranscriptRead | null;
  missing: boolean;
  loading: boolean;
  failed: boolean;
  query: string;
  onQuery: (query: string) => void;
  onRevision: (revisionId: string | null) => void;
  onSaved: () => void;
}

function emptyMessage(transcript: TranscriptRead | null, missing: boolean, failed: boolean) {
  if (transcript) return NO_MATCH;
  if (failed) return null;
  return missing ? "This meeting has no transcript." : "Transcript is not available yet.";
}

export function TranscriptPanel({
  meeting,
  transcript,
  missing,
  loading,
  failed,
  query,
  onQuery,
  onRevision,
  onSaved,
}: TranscriptPanelProps) {
  const editable = transcript?.revision.is_current === true && !isInProgress(meeting.state);
  const [editedBase, setEditedBase] = useState<TranscriptRead | null>(null);
  if (editedBase && !editable) setEditedBase(null);

  const shown = editedBase ?? transcript;
  const segments = matchingSegments(shown, query);
  const showsOriginal = shown?.revision.revision_type === "original";
  const empty = !loading && segments.length === 0 && emptyMessage(shown, missing, failed);

  return (
    // Visible: a Card clips its content, which would keep the edit bar from sticking.
    <Card sx={{ p: { xs: 2, md: 3 }, overflow: "visible" }}>
      <Stack sx={{ gap: 1.5 }}>
        <Stack
          direction="row"
          sx={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 1 }}
        >
          <Typography variant="h2">
            {showsOriginal ? "Original transcript" : shown ? "Edited transcript" : "Transcript"}
          </Typography>
          <Stack direction="row" sx={{ gap: 1, alignItems: "center", ml: "auto" }}>
            {transcript && editable && !editedBase && (
              <Button
                startIcon={<EditOutlinedIcon />}
                onClick={() => setEditedBase(transcript)}
                sx={{ whiteSpace: "nowrap" }}
              >
                Edit transcript
              </Button>
            )}
            <Chip label={shown?.segments.length ?? 0} size="small" />
          </Stack>
        </Stack>
        {shown?.is_edited && !editedBase && (
          <Button onClick={() => onRevision(showsOriginal ? null : shown.original_revision_id)}>
            {showsOriginal ? "View current transcript" : "View original transcript"}
          </Button>
        )}
        <TextField
          size="small"
          placeholder="Search transcript"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
        />
        {editedBase ? (
          <TranscriptEditor
            meeting={meeting}
            base={editedBase}
            segments={segments}
            onClose={() => setEditedBase(null)}
            onSaved={onSaved}
          />
        ) : (
          <Stack sx={{ gap: 1.5 }}>
            {segments.map((item) => (
              <SegmentRow key={item.id} speaker={item.speaker} startSeconds={item.start_seconds}>
                <Typography color="textSecondary">{item.text}</Typography>
              </SegmentRow>
            ))}
            {empty && <Typography color="textSecondary">{empty}</Typography>}
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
