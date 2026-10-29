import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import type { Schemas } from "@/shared/api/types";
import { expectNoContent, unwrap } from "@/shared/api/unwrap";
import { clearSignedInUser, storeSignedInUser } from "../session-storage";

export type Credentials = Omit<Schemas["SignIn"], "kind">;

export function useSignIn() {
  return useMutation({
    mutationFn: (credentials: Credentials) =>
      unwrap(apiClient.POST("/api/v1/sessions", { body: { ...credentials, kind: "browser" } })),
    onSuccess: (session) => storeSignedInUser(session.user),
  });
}

export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => expectNoContent(apiClient.DELETE("/api/v1/sessions/current")),
    onSettled: () => {
      clearSignedInUser();
      queryClient.clear();
    },
  });
}
