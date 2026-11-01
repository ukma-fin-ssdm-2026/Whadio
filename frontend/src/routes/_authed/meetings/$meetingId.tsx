import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { MeetingPage } from "@/app/pages/MeetingPage";
import { MEETING_TABS, type MeetingTab } from "@/features/meetings/model";

export const Route = createFileRoute("/_authed/meetings/$meetingId")({
  validateSearch: z.object({
    tab: z.enum(MEETING_TABS).optional().catch(undefined),
    revision_id: z.string().optional().catch(undefined),
  }),
  component: MeetingRoute,
});

const defaultTab = (revisionId: string | null): MeetingTab => (revisionId ? "transcript" : "notes");

function MeetingRoute() {
  const navigate = Route.useNavigate();
  const { meetingId } = Route.useParams();
  const { tab, revision_id: linkedRevision } = Route.useSearch();
  const revisionId = linkedRevision || null;

  const showTab = (next: MeetingTab, revision: string | null) =>
    navigate({
      search: {
        tab: next === defaultTab(revision) ? undefined : next,
        revision_id: revision ?? undefined,
      },
      resetScroll: false,
    });

  return (
    <MeetingPage
      meetingId={meetingId}
      revisionId={revisionId}
      tab={tab ?? defaultTab(revisionId)}
      onTab={(next) => showTab(next, revisionId)}
      onRevision={(revision) => showTab("transcript", revision)}
    />
  );
}
