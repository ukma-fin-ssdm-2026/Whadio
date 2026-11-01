import { Box, CircularProgress } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ExportMenu } from "@/features/export/components/ExportMenu";
import { isMeetingGone, meetingQueries } from "@/features/meetings/api/meetings";
import { MeetingDetail } from "@/features/meetings/detail/MeetingDetail";
import type { MeetingTab } from "@/features/meetings/model";
import { workspaceQueries } from "@/features/workspaces/api/workspaces";
import { Breadcrumbs } from "../layout/Breadcrumbs";

interface MeetingPageProps {
  meetingId: string;
  revisionId: string | null;
  tab: MeetingTab;
  onTab: (tab: MeetingTab) => void;
  onRevision: (revisionId: string | null) => void;
}

export function MeetingPage({ meetingId, revisionId, tab, onTab, onRevision }: MeetingPageProps) {
  const opened = useQuery(meetingQueries.detail(meetingId));
  const { data: workspaces } = useQuery(workspaceQueries.list());
  const meeting = isMeetingGone(opened.error) ? undefined : opened.data;

  const [transcriptQuery, setTranscriptQuery] = useState("");
  const link = `${meetingId}/${revisionId}`;
  const [shownLink, setShownLink] = useState(link);
  if (link !== shownLink) {
    setShownLink(link);
    setTranscriptQuery("");
  }

  return (
    <>
      <Breadcrumbs
        workspace={workspaces?.find((item) => item.id === meeting?.workspaceId)}
        current={meeting?.title ?? "Meeting"}
      />
      {opened.isError && (
        <Box className="error-banner" role="alert">
          {opened.error.message}
        </Box>
      )}
      {opened.isLoading && (
        <CircularProgress aria-label="Loading meeting" sx={{ alignSelf: "center" }} />
      )}
      {meeting && (
        <MeetingDetail
          meeting={meeting}
          revisionId={revisionId}
          tab={tab}
          transcriptQuery={transcriptQuery}
          onTranscriptQuery={setTranscriptQuery}
          onTab={onTab}
          onRevision={onRevision}
          renderExport={({ transcript, notes }) => (
            <ExportMenu meetingId={meeting.id} tab={tab} transcript={transcript} notes={notes} />
          )}
        />
      )}
    </>
  );
}
