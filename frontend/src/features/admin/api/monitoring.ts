import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import type { Schemas } from "@/shared/api/types";
import { unwrap } from "@/shared/api/unwrap";

export interface JobFilters {
  job_type?: Schemas["JobType"];
  status?: Schemas["JobStatus"];
}
export const ADMIN_KEY = ["admin"] as const;
export const MONITOR_INTERVAL_MS = 10_000;
const freshness = {
  staleTime: 0,
  gcTime: 0,
  refetchOnMount: "always",
  refetchInterval: MONITOR_INTERVAL_MS,
} as const;
export const adminQueries = {
  metrics: () =>
    queryOptions({
      ...freshness,
      queryKey: [...ADMIN_KEY, "metrics"],
      queryFn: ({ signal }) => unwrap(apiClient.GET("/api/v1/admin/metrics", { signal })),
    }),
  jobs: (filters: JobFilters) =>
    infiniteQueryOptions({
      ...freshness,
      queryKey: [...ADMIN_KEY, "jobs", filters],
      initialPageParam: "",
      queryFn: ({ pageParam, signal }) =>
        unwrap(
          apiClient.GET("/api/v1/admin/jobs", {
            params: { query: { ...filters, limit: 25, cursor: pageParam || null } },
            signal,
          }),
        ),
      getNextPageParam: ({ pagination }) => (pagination.has_more ? pagination.next_cursor : null),
    }),
};
