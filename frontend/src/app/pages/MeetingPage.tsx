import { CircularProgress } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { sessionQueries } from "@/features/accounts/api/session";
import { ExportMenu } from "@/features/export/components/ExportMenu";
import { folderQueries } from "@/features/meetings/api/folders";
import { isMeetingGone, meetingQueries } from "@/features/meetings/api/meetings";
import { MeetingActions } from "@/features/meetings/detail/MeetingActions";
import { MeetingDetail } from "@/features/meetings/detail/MeetingDetail";
import type { MeetingTab } from "@/features/meetings/model";
import { workspaceQueries } from "@/features/workspaces/api/workspaces";
import { ErrorBanner } from "@/shared/ui/ErrorBanner";
import { Breadcrumbs } from "../layout/Breadcrumbs";

interface MeetingPageProps {
  meetingId: string;
  revisionId: string | null;
  tab: MeetingTab;
  onTab: (tab: MeetingTab) => void;
  onRevision: (revisionId: string | null) => void;
}

export function MeetingPage({ meetingId, revisionId, tab, onTab, onRevision }: MeetingPageProps) {
  const navigate = useNavigate();
  const opened = useQuery(meetingQueries.detail(meetingId));
  const { data: workspaces } = useQuery(workspaceQueries.list());
  const { data: user } = useQuery(sessionQueries.me());
  const meeting = isMeetingGone(opened.error) ? undefined : opened.data;
  const folders = useQuery({
    ...folderQueries.list(meeting?.workspaceId ?? ""),
    enabled: Boolean(meeting),
  });
  const workspace = workspaces?.find((item) => item.id === meeting?.workspaceId);

  const [transcriptQuery, setTranscriptQuery] = useState("");
  const link = `${meetingId}/${revisionId}`;
  const [shownLink, setShownLink] = useState(link);
  if (link !== shownLink) {
    setShownLink(link);
    setTranscriptQuery("");
  }

  return (
    <>
      <Breadcrumbs workspace={workspace} current={meeting?.title ?? "Meeting"} />
      {opened.isError && <ErrorBanner>{opened.error.message}</ErrorBanner>}
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
          actions={
            workspace &&
            user && (
              <MeetingActions
                meeting={meeting}
                role={workspace.role}
                userId={user.id}
                folders={folders.data ?? []}
                onDeleted={() =>
                  navigate({
                    to: "/workspaces/$workspaceId",
                    params: { workspaceId: meeting.workspaceId },
                    replace: true,
                  })
                }
              />
            )
          }
        />
      )}
    </>
  );
}
