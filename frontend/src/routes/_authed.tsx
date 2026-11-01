import { createFileRoute, redirect } from "@tanstack/react-router";
import { SignedInLayout } from "@/app/layout/SignedInLayout";
import { returnSearch } from "@/app/navigation/return-to";
import { sessionQueries } from "@/features/accounts/api/session";

export const Route = createFileRoute("/_authed")({
  beforeLoad: async ({ context: { queryClient }, location }) => {
    const user = await queryClient.query(sessionQueries.me());
    if (!user) throw redirect({ to: "/sign-in", search: returnSearch(location) });
  },
  component: SignedInLayout,
});
