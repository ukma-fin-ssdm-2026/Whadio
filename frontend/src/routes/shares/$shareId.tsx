import { createFileRoute } from "@tanstack/react-router";
import { ShareLinkPage } from "@/app/pages/ShareLinkPage";

export const Route = createFileRoute("/shares/$shareId")({
  component: ShareLinkRoute,
});

function ShareLinkRoute() {
  const { shareId } = Route.useParams();
  return <ShareLinkPage shareId={shareId} />;
}
