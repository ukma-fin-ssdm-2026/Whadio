import { queryOptions } from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import { unwrap } from "@/shared/api/unwrap";

// The session cookie is HttpOnly, so only the API can say who is signed in.
export const currentUserQuery = () =>
  queryOptions({
    queryKey: ["users", "me"],
    queryFn: ({ signal }) => unwrap(apiClient.GET("/api/v1/users/me", { signal })),
  });
