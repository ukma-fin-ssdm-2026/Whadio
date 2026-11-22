import { useQuery } from "@tanstack/react-query";
import { useLocation, useRouter } from "@tanstack/react-router";
import { useState } from "react";
import { linkToken } from "@/features/accounts/api/account-links";
import { sessionQueries, useSignOut } from "@/features/accounts/api/session";
import { SignInForm } from "@/features/accounts/components/SignInForm";
import { ShareRequest } from "@/features/meetings/sharing/ShareRequest";

export function ShareLinkPage({ shareId }: { shareId: string }) {
  const router = useRouter();
  const hash = useLocation({ select: (location) => location.hash });
  const { data: currentUser, error: sessionError, refetch } = useQuery(sessionQueries.me());
  const signOut = useSignOut();
  const [signIn, setSignIn] = useState<{ sessionRefused?: boolean } | null>(null);
  const [signInUnproven, setSignInUnproven] = useState(false);
  const { queryClient, onSignedIn } = router.options.context;

  if (signIn) {
    return (
      <SignInForm
        sessionRefused={signIn.sessionRefused}
        onSignedIn={() => {
          onSignedIn();
          setSignInUnproven(true);
          setSignIn(null);
        }}
      />
    );
  }

  return (
    <ShareRequest
      key={`${shareId}/${hash}`}
      shareId={shareId}
      token={linkToken(hash)}
      currentUser={currentUser}
      sessionError={sessionError?.message}
      onRetrySession={() => void refetch()}
      onRequestSignIn={() => setSignIn({})}
      onSessionExpired={() => {
        queryClient.setQueryData(sessionQueries.me().queryKey, null);
        setSignIn({ sessionRefused: signInUnproven });
        setSignInUnproven(false);
      }}
      onUseDifferentAccount={async () => {
        await signOut.mutateAsync().catch(() => undefined);
        setSignInUnproven(false);
        setSignIn({});
      }}
      onOpen={() =>
        void router.navigate({ to: "/shared/$shareId", params: { shareId }, replace: true })
      }
      onOpenMeetings={() => void router.navigate({ to: "/meetings", replace: true })}
    />
  );
}
