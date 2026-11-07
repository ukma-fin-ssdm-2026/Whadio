import {
  Alert,
  Button,
  CircularProgress,
  Link,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { PageHeader } from "@/shared/ui/PageHeader";
import { ADMIN_KEY, adminQueries, type JobFilters } from "./api/monitoring";
import { CountsTable } from "./CountsTable";
import { timestamp, title } from "./format";
import { JobList } from "./JobList";
import { adminSearch, JOB_STATUSES, JOB_TYPES } from "./search";

export function AdminPage({
  filters,
  onFilters,
  onForbidden,
  workspaceHref,
}: {
  filters: JobFilters;
  onFilters: (filters: JobFilters) => void;
  onForbidden: () => void;
  workspaceHref: (id: string) => string;
}) {
  const client = useQueryClient();
  const [denied, setDenied] = useState(false);
  const metrics = useQuery({ ...adminQueries.metrics(), enabled: !denied });
  const jobs = useInfiniteQuery({ ...adminQueries.jobs(filters), enabled: !denied });
  const forbidden = metrics.error?.status === 403 || jobs.error?.status === 403;
  useEffect(() => {
    if (!forbidden) return;
    setDenied(true);
    void client
      .cancelQueries({ queryKey: ADMIN_KEY })
      .then(() => client.removeQueries({ queryKey: ADMIN_KEY }));
    onForbidden();
  }, [client, forbidden, onForbidden]);

  if (denied || forbidden)
    return (
      <>
        <PageHeader title="Admin" />
        <Alert severity="error">Not allowed. Administrator permission is required.</Alert>
      </>
    );
  if (metrics.error?.status === 401 || jobs.error?.status === 401) return null;
  const busy = metrics.isFetching || jobs.isFetching;
  const pages = jobs.data?.pages.map((page) => page.items) ?? [];
  const empty = pages.every((page) => page.length === 0);
  const refresh = () => {
    void metrics.refetch();
    void jobs.refetch();
  };
  return (
    <Stack sx={{ gap: 2 }}>
      <PageHeader
        title="Admin"
        description="Processing jobs across this instance"
        actions={
          <Button onClick={refresh} disabled={busy}>
            Refresh
          </Button>
        }
      />
      <Typography variant="body2" color="textSecondary">
        Updates every 10 seconds while this page is visible. Counts cover retained jobs.
      </Typography>
      {metrics.error && (
        <Alert severity="warning">
          Metrics could not be refreshed. {metrics.data && "Showing the last successful snapshot."}{" "}
          Use Refresh to retry.
        </Alert>
      )}
      {metrics.isPending && !metrics.error && (
        <CircularProgress aria-label="Loading metrics" size={24} />
      )}
      {metrics.data && (
        <>
          <Typography variant="body2">
            Counts updated {timestamp(metrics.data.generated_at)}
          </Typography>
          {metrics.data.jobs.length > 0 && <CountsTable counts={metrics.data.jobs} />}
          {metrics.data.jobs.length === 0 && <Alert severity="info">No retained jobs.</Alert>}
        </>
      )}
      <Typography variant="h2">Jobs</Typography>
      <Stack direction={{ xs: "column", sm: "row" }} sx={{ gap: 2 }}>
        <TextField
          select
          label="Job type"
          value={filters.job_type ?? ""}
          onChange={(event) =>
            onFilters({
              ...filters,
              job_type: adminSearch.shape.job_type.parse(event.target.value),
            })
          }
          sx={{ minWidth: 180 }}
        >
          <MenuItem value="">All types</MenuItem>
          {JOB_TYPES.map((type) => (
            <MenuItem key={type} value={type}>
              {title(type)}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          label="State"
          value={filters.status ?? ""}
          onChange={(event) => {
            const value = event.target.value;
            onFilters({
              ...filters,
              status: adminSearch.shape.status.parse(value),
            });
          }}
          sx={{ minWidth: 180 }}
        >
          <MenuItem value="">All states</MenuItem>
          {JOB_STATUSES.map((status) => (
            <MenuItem key={status} value={status}>
              {title(status)}
            </MenuItem>
          ))}
        </TextField>
      </Stack>
      {filters.workspace_id && (
        <Stack direction="row" sx={{ gap: 1, alignItems: "center", flexWrap: "wrap" }}>
          <Typography variant="body2" sx={{ overflowWrap: "anywhere" }}>
            Workspace filter: {filters.workspace_id}
          </Typography>
          <Link
            component="button"
            onClick={() => onFilters({ ...filters, workspace_id: undefined })}
          >
            Clear workspace filter
          </Link>
        </Stack>
      )}
      {jobs.error && (
        <Alert severity="warning">
          Jobs could not be loaded or refreshed.{" "}
          {jobs.data && "Previously loaded jobs remain below with their observation times."}{" "}
          <Button
            onClick={() => (jobs.isFetchNextPageError ? jobs.fetchNextPage() : jobs.refetch())}
          >
            Retry jobs
          </Button>
        </Alert>
      )}
      {jobs.isPending && !jobs.error && <CircularProgress aria-label="Loading jobs" size={24} />}
      {jobs.isSuccess && empty && <Alert severity="info">No jobs match these filters.</Alert>}
      <JobList
        pages={pages}
        workspaceHref={workspaceHref}
        onWorkspace={(workspace_id) => onFilters({ ...filters, workspace_id })}
      />
      {jobs.hasNextPage && (
        <Button onClick={() => jobs.fetchNextPage()} disabled={jobs.isFetching}>
          Load more
        </Button>
      )}
    </Stack>
  );
}
