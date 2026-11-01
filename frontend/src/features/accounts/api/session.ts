import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import type { Schemas } from "@/shared/api/types";
import { expectNoContent, unwrap } from "@/shared/api/unwrap";
import { currentUserQuery } from "./current-user";

export type Credentials = Omit<Schemas["SignIn"], "kind">;

export function useSignIn() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (credentials: Credentials) =>
      unwrap(apiClient.POST("/api/v1/sessions", { body: { ...credentials, kind: "browser" } })),
    onSuccess: (session) => queryClient.setQueryData(currentUserQuery().queryKey, session.user),
  });
}

export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => expectNoContent(apiClient.DELETE("/api/v1/sessions/current")),
    onSettled: () => queryClient.clear(),
  });
}
