import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Breadcrumbs } from "@/app/layout/Breadcrumbs";
import { SharedWithMe } from "@/features/meetings/sharing/SharedWithMe";
import { PageHeader } from "@/shared/ui/PageHeader";

export const Route = createFileRoute("/_authed/shared/")({
  component: SharedWithMeRoute,
});

function SharedWithMeRoute() {
  const navigate = useNavigate();
  return (
    <>
      <Breadcrumbs current="Shared with me" />
      <PageHeader title="Shared with me" />
      <SharedWithMe
        onOpen={(shareId) => void navigate({ to: "/shared/$shareId", params: { shareId } })}
      />
    </>
  );
}
