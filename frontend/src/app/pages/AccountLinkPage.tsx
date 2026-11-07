import { useLocation, useRouter } from "@tanstack/react-router";
import { linkToken } from "@/features/accounts/api/account-links";
import { sessionQueries } from "@/features/accounts/api/session";
import { AccountLinkForm } from "@/features/accounts/components/AccountLinkForm";

export function AccountLinkPage({ kind, id }: { kind: "registration" | "reset"; id: string }) {
  const router = useRouter();
  const hash = useLocation({ select: (location) => location.hash });
  const { queryClient, onSignedIn } = router.options.context;
  return (
    <AccountLinkForm
      key={`${kind}/${id}/${hash}`}
      kind={kind}
      id={id}
      token={linkToken(hash)}
      termsHref={router.buildLocation({ to: "/terms" }).href}
      signInHref={router.buildLocation({ to: "/sign-in" }).href}
      onComplete={async (user) => {
        await queryClient.cancelQueries();
        queryClient.clear();
        queryClient.setQueryData(sessionQueries.me().queryKey, user ?? null);
        if (user) onSignedIn();
        await router.navigate({
          to: user ? "/" : "/sign-in",
          search: user ? {} : { passwordReset: true },
          replace: true,
        });
      }}
    />
  );
}
