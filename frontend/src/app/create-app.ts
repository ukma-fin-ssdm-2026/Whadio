import { createRouter } from "@tanstack/react-router";
import { sessionQueries } from "@/features/accounts/api/session";
import { routeTree } from "@/routeTree.gen";
import { LoadingScreen } from "./layout/CenteredScreen";
import { NotFoundPage } from "./layout/NotFoundPage";
import { RouteError } from "./layout/RouteError";
import { returnSearch } from "./navigation/return-to";
import { createQueryClient } from "./query-client";

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createApp>["router"];
  }
}

declare module "@tanstack/history" {
  interface HistoryState {
    sessionRefused?: boolean;
  }
}

const SPINNER_DELAY_MS = 200;

export function createApp(basepath = import.meta.env.BASE_URL) {
  let signInUnproven = false;

  const endSession = () => {
    const sessionRefused = signInUnproven;
    signInUnproven = false;
    queryClient.setQueryData(sessionQueries.me().queryKey, null);
    const location = router.latestLocation;
    // The queries still mounted while the page leaves can answer 401 a second time.
    if (location.pathname === "/sign-in") return;
    // Cleared only once the page has gone: a mounted query refetches whatever is cleared under it.
    void router
      .navigate({
        to: "/sign-in",
        search: returnSearch(location),
        state: (state) => ({ ...state, sessionRefused }),
        replace: true,
      })
      .then(() => queryClient.clear());
  };

  const queryClient = createQueryClient({
    onUnauthorized: endSession,
    onDataLoaded: () => {
      signInUnproven = false;
    },
  });

  const router = createRouter({
    routeTree,
    basepath,
    context: {
      queryClient,
      onSignedIn: () => {
        signInUnproven = true;
      },
    },
    defaultNotFoundComponent: NotFoundPage,
    defaultErrorComponent: RouteError,
    defaultPendingComponent: LoadingScreen,
    defaultPendingMs: SPINNER_DELAY_MS,
    defaultPendingMinMs: 0,
  });

  return { queryClient, router };
}
