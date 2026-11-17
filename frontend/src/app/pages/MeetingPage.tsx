import { CircularProgress } from "@mui/material";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { sessionQueries } from "@/features/accounts/api/session";
import { ExportMenu } from "@/features/export/components/ExportMenu";
import { folderQueries } from "@/features/meetings/api/folders";
import { isMeetingGone, meetingQueries } from "@/features/meetings/api/meetings";
import { GeneratedNamePrompt } from "@/features/meetings/detail/GeneratedNamePrompt";
import { MeetingActions } from "@/features/meetings/detail/MeetingActions";
import { MeetingDetail } from "@/features/meetings/detail/MeetingDetail";
import type { MeetingTab } from "@/features/meetings/model";
import { memberQueries } from "@/features/members/api/members";
import { workspaceQueries } from "@/features/workspaces/api/workspaces";
import { WorkspacePresetSelect } from "@/features/workspaces/components/WorkspacePresetSelect";
import { canManage } from "@/shared/lib/roles";
import { ErrorBanner } from "@/shared/ui/ErrorBanner";
import { Breadcrumbs } from "../layout/Breadcrumbs";

interface MeetingPageProps {
  meetingId: string;
  revisionId: string | null;
  tab: MeetingTab;
  onTab: (tab: MeetingTab) => void;
  onRevision: (revisionId: string | null) => void;
  onUnsavedChange: (unsaved: boolean) => void;
}

export function MeetingPage({
  meetingId,
  revisionId,
  tab,
  onTab,
  onRevision,
  onUnsavedChange,
}: MeetingPageProps) {
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
  const [accessOpen, setAccessOpen] = useState(false);
  const members = useInfiniteQuery({
    ...memberQueries.list(meeting?.workspaceId ?? ""),
    enabled: Boolean(
      accessOpen && meeting && workspace && !workspace.personal && canManage(workspace.role),
    ),
  });
  const { hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } = members;
  useEffect(() => {
    if (accessOpen && hasNextPage && !isFetchingNextPage && !isFetchNextPageError) {
      void fetchNextPage();
    }
  }, [accessOpen, hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage]);

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
          onUnsavedChange={onUnsavedChange}
          renderExport={({ transcript, notes }) => (
            <ExportMenu meetingId={meeting.id} tab={tab} transcript={transcript} notes={notes} />
          )}
          renderPresetField={(field) => (
            <WorkspacePresetSelect workspaceId={meeting.workspaceId} {...field} />
          )}
          actions={
            workspace &&
            user && (
              <MeetingActions
                meeting={meeting}
                role={workspace.role}
                userId={user.id}
                personal={workspace.personal}
                folders={folders.data ?? []}
                members={{ data: hasNextPage ? undefined : members.data, error: members.error }}
                onAccessOpen={setAccessOpen}
                onLeave={() =>
                  navigate({
                    to: "/workspaces/$workspaceId",
                    params: { workspaceId: meeting.workspaceId },
                    replace: true,
                  })
                }
              />
            )
          }
          namePrompt={
            user?.id === meeting.createdByUserId && (
              <GeneratedNamePrompt key={meeting.id} meeting={meeting} />
            )
          }
        />
      )}
    </>
  );
}
