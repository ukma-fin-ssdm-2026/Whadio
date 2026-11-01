import { createFileRoute, useLocation } from "@tanstack/react-router";
import { z } from "zod";
import { MeetingPage } from "@/app/pages/MeetingPage";

export const Route = createFileRoute("/_authed/meetings/$meetingId")({
  validateSearch: z.object({ revision_id: z.string().optional().catch(undefined) }),
  component: MeetingRoute,
});

function MeetingRoute() {
  const navigate = Route.useNavigate();
  const { meetingId } = Route.useParams();
  const { revision_id: revisionId } = Route.useSearch();
  const linkedTab = useLocation({ select: (location) => location.state.meetingTab });
  return (
    <MeetingPage
      meetingId={meetingId}
      revisionId={revisionId || null}
      linkedTab={linkedTab}
      onRevision={(revision) =>
        navigate({
          search: revision ? { revision_id: revision } : {},
          state: (state) => ({ ...state, meetingTab: "transcript" }),
        })
      }
    />
  );
}
