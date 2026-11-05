import { useQuery } from "@tanstack/react-query";
import { useLocation, useRouter } from "@tanstack/react-router";
import { useState } from "react";
import { linkToken } from "@/features/accounts/api/account-links";
import { sessionQueries, useSignOut } from "@/features/accounts/api/session";
import { SignInForm } from "@/features/accounts/components/SignInForm";
import { InvitationRedemption } from "@/features/invitations/components/InvitationRedemption";
import type { Schemas } from "@/shared/api/types";

export function InvitationPage({ invitationId }: { invitationId: string }) {
  const router = useRouter();
  const hash = useLocation({ select: (location) => location.hash });
  const { data: currentUser, error: sessionError, refetch } = useQuery(sessionQueries.me());
  const signOut = useSignOut();
  const [signingIn, setSigningIn] = useState(false);
  const { queryClient, onSignedIn } = router.options.context;

  if (signingIn) {
    return (
      <SignInForm
        onSignedIn={() => {
          onSignedIn();
          setSigningIn(false);
        }}
      />
    );
  }

  const finishJoining = async (workspaceId: string, user?: Schemas["UserRead"]) => {
    if (user) {
      await queryClient.cancelQueries();
      queryClient.clear();
      queryClient.setQueryData(sessionQueries.me().queryKey, user);
      onSignedIn();
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["workspaces"] }),
      queryClient.invalidateQueries({ queryKey: sessionQueries.me().queryKey }),
    ]);
    await router.navigate({
      to: "/workspaces/$workspaceId",
      params: { workspaceId },
      replace: true,
    });
  };

  return (
    <InvitationRedemption
      key={`${invitationId}/${hash}`}
      id={invitationId}
      token={linkToken(hash)}
      currentUser={currentUser}
      sessionError={sessionError?.message}
      onRetrySession={() => void refetch()}
      termsHref={router.buildLocation({ to: "/terms" }).href}
      onRequestSignIn={() => setSigningIn(true)}
      onUseDifferentAccount={async () => {
        await signOut.mutateAsync().catch(() => undefined);
        setSigningIn(true);
      }}
      onJoined={finishJoining}
    />
  );
}
