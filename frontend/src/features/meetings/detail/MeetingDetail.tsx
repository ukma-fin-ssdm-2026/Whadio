import { Box, Stack, Tab, Tabs } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { Fragment, type ReactNode, useId } from "react";
import type { NoteRead, TranscriptRead } from "@/shared/api/types";
import { formatDate } from "@/shared/lib/format";
import { PageHeader } from "@/shared/ui/PageHeader";
import { meetingQueries } from "../api/meetings";
import type { Meeting, MeetingTab } from "../model";
import { NotesPanel } from "./NotesPanel";
import { RecordingPlayer } from "./RecordingPlayer";
import { TranscriptPanel } from "./TranscriptPanel";

interface MeetingContent {
  transcript: TranscriptRead | null;
  notes: NoteRead | null;
}

interface MeetingDetailProps {
  meeting: Meeting;
  revisionId: string | null;
  tab: MeetingTab;
  transcriptQuery: string;
  onTab: (tab: MeetingTab) => void;
  onTranscriptQuery: (query: string) => void;
  onRevision: (revisionId: string | null) => void;
  renderExport: (content: MeetingContent) => ReactNode;
}

export function MeetingDetail({
  meeting,
  revisionId,
  tab,
  transcriptQuery,
  onTab,
  onTranscriptQuery,
  onRevision,
  renderExport,
}: MeetingDetailProps) {
  const id = useId();
  const notesResult = useQuery(meetingQueries.notes(meeting));
  const transcriptResult = useQuery(meetingQueries.transcript(meeting, revisionId));
  const notes = notesResult.data ?? null;
  const transcript = transcriptResult.data ?? null;

  const notTranscribed = transcriptResult.error?.code === "NOT_TRANSCRIBED" && !revisionId;
  const contentError = notesResult.error ?? (notTranscribed ? null : transcriptResult.error);

  const tabProps = (value: MeetingTab) => ({
    value,
    id: `${id}-${value}-tab`,
    "aria-controls": `${id}-panel`,
  });

  return (
    <Stack sx={{ gap: 2 }}>
      {contentError && (
        <Box className="error-banner" role="alert">
          {contentError.message}
        </Box>
      )}
      <PageHeader
        title={meeting.title}
        description={`${formatDate(meeting.date)} · ${meeting.source}`}
        actions={
          <Fragment key={`${meeting.id}-${tab}-${transcript?.revision.id}`}>
            {renderExport({ transcript, notes })}
          </Fragment>
        }
      />
      <Tabs value={tab} onChange={(_, value) => onTab(value)} className="meeting-tabs">
        <Tab label="Notes" {...tabProps("notes")} />
        <Tab label="Transcript" {...tabProps("transcript")} />
        <Tab label="Recording" {...tabProps("recording")} />
      </Tabs>

      <Box role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${tab}-tab`}>
        {tab === "notes" ? (
          <NotesPanel meeting={meeting} notes={notes} loading={notesResult.isLoading} />
        ) : (
          <Box
            sx={{
              display: "grid",
              gap: 2,
              alignItems: "start",
              gridTemplateColumns: {
                md: tab === "recording" ? "minmax(0, 3fr) minmax(0, 2fr)" : "minmax(0, 1fr)",
              },
            }}
          >
            {tab === "recording" && <RecordingPlayer meeting={meeting} />}
            <TranscriptPanel
              transcript={transcript}
              loading={transcriptResult.isLoading}
              query={transcriptQuery}
              onQuery={onTranscriptQuery}
              onRevision={onRevision}
            />
          </Box>
        )}
      </Box>
    </Stack>
  );
}
