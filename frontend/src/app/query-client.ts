import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/shared/api/errors";

declare module "@tanstack/react-query" {
  interface Register {
    defaultError: ApiError;
  }
}

const MAX_RETRIES = 2;

export function retryUnlessClientError(failureCount: number, error: Error): boolean {
  const clientError = error instanceof ApiError && error.status >= 400 && error.status < 500;
  return !clientError && failureCount < MAX_RETRIES;
}

// A wrong password is a 401 too, and it ends no session.
const endsSession = (error: unknown) =>
  error instanceof ApiError && error.status === 401 && error.code !== "INVALID_CREDENTIALS";

interface QueryClientHandlers {
  onUnauthorized: () => void;
  onDataLoaded: () => void;
}

export function createQueryClient({
  onUnauthorized,
  onDataLoaded,
}: QueryClientHandlers): QueryClient {
  const handleError = (error: unknown) => {
    if (endsSession(error)) onUnauthorized();
  };
  return new QueryClient({
    queryCache: new QueryCache({ onError: handleError, onSuccess: onDataLoaded }),
    mutationCache: new MutationCache({ onError: handleError }),
    defaultOptions: {
      queries: { retry: retryUnlessClientError, staleTime: 30_000 },
    },
  });
}
