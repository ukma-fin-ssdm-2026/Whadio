import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { Schemas } from "@/shared/api/types";
import { formatDuration } from "@/shared/lib/format-duration";
import { PageHeader } from "@/shared/ui/PageHeader";
import { ADMIN_KEY, adminQueries, type JobFilters } from "./api/monitoring";

const duration = (value: number | null) =>
  value === null ? "Unknown" : formatDuration(Math.floor(value));
const title = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);
const timestamp = (value: string) => new Date(value).toLocaleString();

function Counts({ counts }: { counts: Schemas["JobCounts"] }) {
  const values = [
    ["Queued", counts.queued],
    ["Running", counts.running],
    ["Failed", counts.failed],
    ["Not yet published", counts.unpublished],
    ["Oldest known queue wait", duration(counts.oldest_queue_wait_seconds)],
    ["Unknown queue waits", counts.unknown_queue_waits],
  ];
  return (
    <Paper variant="outlined" sx={{ p: 2, flex: 1 }}>
      <Typography variant="h3" component="h2" sx={{ mb: 2 }}>
        {title(counts.job_type)}
      </Typography>
      <Box component="dl" sx={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 1, m: 0 }}>
        {values.map(([label, value]) => (
          <Box key={label} sx={{ display: "contents" }}>
            <Typography component="dt" color="textSecondary">
              {label}
            </Typography>
            <Typography component="dd" sx={{ m: 0, fontVariantNumeric: "tabular-nums" }}>
              {value}
            </Typography>
          </Box>
        ))}
      </Box>
    </Paper>
  );
}

function Job({ job }: { job: Schemas["JobSnapshot"] }) {
  const timing =
    job.status === "queued"
      ? `Waiting: ${duration(job.queue_wait_seconds)}`
      : job.status === "running"
        ? `Running: ${duration(job.running_seconds)}`
        : `Last attempt: ${duration(job.last_attempt_duration_seconds)}`;
  return (
    <Paper component="li" variant="outlined" sx={{ p: 2, listStyle: "none" }}>
      <Stack direction="row" sx={{ gap: 1, alignItems: "center", flexWrap: "wrap", mb: 1 }}>
        <Typography variant="h3" component="h3">
          {title(job.job_type)}
        </Typography>
        <Chip
          size="small"
          label={title(job.status)}
          color={job.status === "failed" ? "error" : "default"}
        />
      </Stack>
      <Typography sx={{ overflowWrap: "anywhere" }}>Workspace: {job.workspace_id}</Typography>
      <Typography>
        {timing} · Attempts: {job.attempts_started}
      </Typography>
      {job.failure_description && (
        <Typography color="error.main">{job.failure_description}</Typography>
      )}
      {job.timing_anomaly && (
        <Typography color="textSecondary">Timing adjusted for clock skew.</Typography>
      )}
      <Typography variant="body2" color="textSecondary">
        Created {timestamp(job.created_at)} · Observed {timestamp(job.as_of)}
      </Typography>
    </Paper>
  );
}

export function AdminPage({
  filters,
  onFilters,
  onForbidden,
}: {
  filters: JobFilters;
  onFilters: (filters: JobFilters) => void;
  onForbidden: () => void;
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
  const rows = jobs.data?.pages.flatMap((page) => page.items) ?? [];
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
            Counts assembled {timestamp(metrics.data.generated_at)}
          </Typography>
          <Stack direction={{ xs: "column", sm: "row" }} sx={{ gap: 2 }}>
            {metrics.data.jobs.map((counts) => (
              <Counts key={counts.job_type} counts={counts} />
            ))}
          </Stack>
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
              job_type:
                event.target.value === "transcription" || event.target.value === "notes"
                  ? event.target.value
                  : undefined,
            })
          }
          sx={{ minWidth: 180 }}
        >
          <MenuItem value="">All types</MenuItem>
          <MenuItem value="transcription">Transcription</MenuItem>
          <MenuItem value="notes">Notes</MenuItem>
        </TextField>
        <TextField
          select
          label="State"
          value={filters.status ?? ""}
          onChange={(event) => {
            const value = event.target.value;
            onFilters({
              ...filters,
              status:
                value === "queued" ||
                value === "running" ||
                value === "succeeded" ||
                value === "failed"
                  ? value
                  : undefined,
            });
          }}
          sx={{ minWidth: 180 }}
        >
          <MenuItem value="">All states</MenuItem>
          {["queued", "running", "succeeded", "failed"].map((status) => (
            <MenuItem key={status} value={status}>
              {title(status)}
            </MenuItem>
          ))}
        </TextField>
      </Stack>
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
      {jobs.isSuccess && rows.length === 0 && (
        <Alert severity="info">No jobs match these filters.</Alert>
      )}
      <Stack component="ul" sx={{ gap: 1, p: 0, m: 0 }}>
        {rows.map((job) => (
          <Job key={job.job_id} job={job} />
        ))}
      </Stack>
      {jobs.hasNextPage && (
        <Button onClick={() => jobs.fetchNextPage()} disabled={jobs.isFetching}>
          Load more
        </Button>
      )}
    </Stack>
  );
}
