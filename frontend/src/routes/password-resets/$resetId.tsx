import { createFileRoute } from "@tanstack/react-router";
import { AccountLinkPage } from "@/app/pages/AccountLinkPage";

export const Route = createFileRoute("/password-resets/$resetId")({
  component: ResetRoute,
});

function ResetRoute() {
  const { resetId } = Route.useParams();
  return <AccountLinkPage kind="reset" id={resetId} />;
}
