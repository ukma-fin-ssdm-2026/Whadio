import { createFileRoute } from "@tanstack/react-router";
import { AccountLinkPage } from "@/app/pages/AccountLinkPage";

export const Route = createFileRoute("/registrations/$registrationId")({
  component: RegistrationRoute,
});

function RegistrationRoute() {
  const { registrationId } = Route.useParams();
  return <AccountLinkPage kind="registration" id={registrationId} />;
}
