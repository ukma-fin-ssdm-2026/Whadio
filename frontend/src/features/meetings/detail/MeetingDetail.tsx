import { Box, Stack, Tab, Tabs } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { Fragment, type ReactNode, useEffect, useId } from "react";
import type { NoteRead, TranscriptRead } from "@/shared/api/types";
import { formatDate } from "@/shared/lib/format";
import { PageHeader } from "@/shared/ui/PageHeader";
import { meetingQueries, TRANSCRIPT_PENDING, useForgetRecordingLink } from "../api/meetings";
import { isInProgress, type Meeting, type MeetingTab } from "../model";
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
  const { data: transcriptAnswer, refetch: refetchTranscript } = transcriptResult;
  const notes = notesResult.data ?? null;
  const transcriptPending = transcriptAnswer === TRANSCRIPT_PENDING;
  const transcript = transcriptPending ? null : (transcriptAnswer ?? null);
  const meetingEnded = !isInProgress(meeting.state);

  // `enabled` stays on past `processing`, so nothing else would ask again until `staleTime`.
  useEffect(() => {
    if (transcriptPending && meetingEnded) refetchTranscript();
  }, [transcriptPending, meetingEnded, refetchTranscript]);

  useForgetRecordingLink(meeting);

  const contentError = notesResult.error ?? transcriptResult.error;

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
          <NotesPanel
            meeting={meeting}
            notes={notes}
            loading={notesResult.isLoading}
            failed={notesResult.isError}
          />
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
            {tab === "recording" && <RecordingPlayer key={meeting.id} meeting={meeting} />}
            <TranscriptPanel
              transcript={transcript}
              missing={transcriptAnswer === null}
              loading={transcriptResult.isLoading}
              failed={transcriptResult.isError}
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
