import { createFileRoute, redirect, useLocation, useRouter } from "@tanstack/react-router";
import { z } from "zod";
import { safeReturnPath } from "@/app/navigation/return-to";
import { sessionQueries } from "@/features/accounts/api/session";
import { SignInForm } from "@/features/accounts/components/SignInForm";

const SESSION_REFUSED =
  "You signed in, but the server did not accept the session. Check that this browser allows cookies, then try again.";

export const Route = createFileRoute("/sign-in")({
  validateSearch: z.object({ redirect: z.string().optional().catch(undefined) }),
  beforeLoad: async ({ context: { queryClient }, search }) => {
    // With the check unavailable the form still works, and signing in reports the failure.
    const user = await queryClient.query(sessionQueries.me()).catch(() => null);
    if (user) throw redirect({ href: safeReturnPath(search.redirect) });
  },
  component: SignInRoute,
});

function SignInRoute() {
  const router = useRouter();
  const { redirect: target } = Route.useSearch();
  const { onSignedIn } = Route.useRouteContext();
  const refused = useLocation({ select: (location) => location.state.sessionRefused });

  return (
    <SignInForm
      externalError={refused ? SESSION_REFUSED : undefined}
      onSignedIn={() => {
        onSignedIn();
        void router.navigate({ href: safeReturnPath(target), replace: true });
      }}
    />
  );
}
