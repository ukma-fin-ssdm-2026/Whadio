import { queryOptions } from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import { unwrap } from "@/shared/api/unwrap";

export const instanceQuery = () =>
  queryOptions({
    queryKey: ["accounts", "instance"],
    queryFn: ({ signal }) => unwrap(apiClient.GET("/api/v1/instance", { signal })),
    meta: { public: true },
    retry: false,
  });
