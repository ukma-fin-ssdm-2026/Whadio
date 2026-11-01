import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import { ApiError } from "@/shared/api/errors";
import type { Schemas } from "@/shared/api/types";
import { expectNoContent, unwrap } from "@/shared/api/unwrap";

export type Credentials = Omit<Schemas["SignIn"], "kind">;

async function fetchSignedInUser(signal: AbortSignal) {
  try {
    return await unwrap(apiClient.GET("/api/v1/users/me", { signal }));
  } catch (error) {
    // The answer to "who is signed in?", not a session ending, so it never reaches the query
    // client's 401 handling, which would otherwise clear this query while the guard awaits it.
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export const sessionQueries = {
  // Every other request notices an expired session, so this never needs to ask again.
  me: () =>
    queryOptions({
      queryKey: ["accounts", "me"],
      queryFn: ({ signal }) => fetchSignedInUser(signal),
      staleTime: Number.POSITIVE_INFINITY,
    }),
};

export function useSignIn() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (credentials: Credentials) =>
      unwrap(apiClient.POST("/api/v1/sessions", { body: { ...credentials, kind: "browser" } })),
    onSuccess: (session) => queryClient.setQueryData(sessionQueries.me().queryKey, session.user),
  });
}

export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => expectNoContent(apiClient.DELETE("/api/v1/sessions/current")),
    onSettled: () => {
      queryClient.clear();
      // A refused sign-out leaves the cookie, and asking again would sign the user straight back in.
      queryClient.setQueryData(sessionQueries.me().queryKey, null);
    },
  });
}
