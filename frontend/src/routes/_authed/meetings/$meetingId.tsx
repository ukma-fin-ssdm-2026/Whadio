import { createFileRoute, useBlocker } from "@tanstack/react-router";
import { useCallback, useRef } from "react";
import { z } from "zod";
import { MeetingPage } from "@/app/pages/MeetingPage";
import { MEETING_TABS, type MeetingTab } from "@/features/meetings/model";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";

export const Route = createFileRoute("/_authed/meetings/$meetingId")({
  validateSearch: z.object({
    tab: z.enum(MEETING_TABS).optional().catch(undefined),
    revision_id: z.string().optional().catch(undefined),
  }),
  component: MeetingRoute,
});

const defaultTab = (revisionId: string | null): MeetingTab => (revisionId ? "transcript" : "notes");

const shownTab = ({ tab, revision_id }: { tab?: MeetingTab; revision_id?: string }) =>
  tab ?? defaultTab(revision_id || null);

function MeetingRoute() {
  const navigate = Route.useNavigate();
  const { meetingId } = Route.useParams();
  const { tab, revision_id: linkedRevision } = Route.useSearch();
  const revisionId = linkedRevision || null;

  const unsaved = useRef(false);
  const reportUnsaved = useCallback((value: boolean) => {
    unsaved.current = value;
  }, []);
  // The transcript editor stays mounted on the recording tab and goes away on the notes tab.
  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) =>
      unsaved.current &&
      (next.routeId !== Route.id ||
        next.pathname !== current.pathname ||
        shownTab(next.search) === "notes"),
    enableBeforeUnload: () => unsaved.current,
    withResolver: true,
  });

  const showTab = (next: MeetingTab, revision: string | null) =>
    navigate({
      search: {
        tab: next === defaultTab(revision) ? undefined : next,
        revision_id: revision ?? undefined,
      },
      resetScroll: false,
    });

  return (
    <>
      <MeetingPage
        meetingId={meetingId}
        revisionId={revisionId}
        tab={tab ?? defaultTab(revisionId)}
        onTab={(next) => showTab(next, revisionId)}
        onRevision={(revision) => showTab("transcript", revision)}
        onUnsavedChange={reportUnsaved}
      />
      <ConfirmDialog
        open={blocker.status === "blocked"}
        title="Discard unsaved changes?"
        confirmLabel="Discard changes"
        destructive
        onConfirm={() => blocker.proceed?.()}
        onCancel={() => blocker.reset?.()}
      >
        Your changes to this transcript have not been saved.
      </ConfirmDialog>
    </>
  );
}
