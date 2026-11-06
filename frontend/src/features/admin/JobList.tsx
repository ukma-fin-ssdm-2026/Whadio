import ContentCopyOutlinedIcon from "@mui/icons-material/ContentCopyOutlined";
import {
  Box,
  Chip,
  IconButton,
  Link,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import type { Schemas } from "@/shared/api/types";
import { formatDuration } from "@/shared/lib/format-duration";
import { useNotify } from "@/shared/ui/NotifyProvider";

import type { JobFilters } from "./api/monitoring";

type Job = Schemas["JobSnapshot"];
const duration = (value: number | null) =>
  value === null ? "Unknown" : formatDuration(Math.floor(value));
const timestamp = (value: string) => new Date(value).toLocaleString();
const title = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);
const timing = (job: Job) =>
  job.status === "queued"
    ? `Waiting: ${duration(job.queue_wait_seconds)}`
    : job.status === "running"
      ? `Running: ${duration(job.running_seconds)}`
      : job.attempts_started === 0
        ? "Not started"
        : `Last attempt: ${duration(job.last_attempt_duration_seconds)}`;

function Identifier({
  id,
  kind,
  onWorkspace,
  filters,
  compact = false,
}: {
  id: string;
  kind: "Job" | "Workspace";
  compact?: boolean;
  onWorkspace: (id: string) => void;
  filters: JobFilters;
}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) search.set(key, value);
  search.set("workspace_id", id);
  const notify = useNotify();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      notify(`${kind} ID copied`);
    } catch {
      notify(`Could not copy. Copy this ${kind.toLowerCase()} ID manually: ${id}`, "error");
    }
  };
  return (
    <Box sx={{ display: "inline-flex", gap: 0.5, alignItems: "center", whiteSpace: "nowrap" }}>
      {kind === "Workspace" ? (
        <Tooltip title={`Filter by workspace ${id}`} arrow>
          <Link
            href={`/admin?${search}`}
            onClick={(event) => {
              if (
                event.button === 0 &&
                !event.ctrlKey &&
                !event.metaKey &&
                !event.shiftKey &&
                !event.altKey
              ) {
                event.preventDefault();
                onWorkspace(id);
              }
            }}
            aria-label={`Filter by workspace ${id}`}
            sx={{ fontFamily: "monospace", fontSize: "inherit" }}
          >
            {!compact && "Workspace: "}
            {id.slice(0, 8)}
          </Link>
        </Tooltip>
      ) : (
        <Typography component="span" variant="body2" sx={{ fontFamily: "monospace" }}>
          {!compact && "Job: "}
          {id.slice(0, 8)}
        </Typography>
      )}
      <Tooltip title={id} arrow>
        <IconButton size="small" onClick={copy} aria-label={`Copy ${kind.toLowerCase()} ID ${id}`}>
          <ContentCopyOutlinedIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Box>
  );
}

function Status({ job }: { job: Job }) {
  return (
    <Chip
      size="small"
      label={title(job.status)}
      color={job.status === "failed" ? "error" : "default"}
    />
  );
}

function AttemptTime({ job }: { job: Job }) {
  if (job.status === "running")
    return (
      <Typography variant="caption" component="div">
        Started {job.started_at === null ? "Unknown" : timestamp(job.started_at)}
      </Typography>
    );
  if (job.status === "failed" || job.status === "succeeded")
    return (
      <Typography variant="caption" component="div">
        Finished {job.finished_at === null ? "Unknown" : timestamp(job.finished_at)}
      </Typography>
    );
  return null;
}

function PreviousWait({ job }: { job: Job }) {
  return job.attempts_started > 0 && job.status !== "queued" ? (
    <>Queue before attempt: {duration(job.last_queue_wait_seconds)}</>
  ) : null;
}

export function JobList({
  pages,
  onWorkspace,
  filters,
}: {
  pages: Job[][];
  onWorkspace: (id: string) => void;
  filters: JobFilters;
}) {
  const desktop = useMediaQuery(useTheme().breakpoints.up("sm"));
  if (pages.every((page) => page.length === 0)) return null;
  if (desktop)
    return (
      <Stack sx={{ gap: 2 }}>
        {pages.map(
          (page, index) =>
            page.length > 0 && (
              <Stack key={page[0]?.job_id ?? index} sx={{ gap: 1 }}>
                <Typography variant="body2" color="textSecondary">
                  Jobs observed {timestamp(page[0]?.as_of ?? "")}
                </Typography>
                <TableContainer component={Paper} variant="outlined">
                  <Table
                    size="small"
                    aria-label="Processing jobs"
                    sx={{
                      minWidth: 1000,
                      tableLayout: "fixed",
                      "& td": { verticalAlign: "top" },
                      "& th, & td": { px: 1 },
                      "& th:nth-of-type(3), & td:nth-of-type(3)": {
                        px: 2.5,
                        verticalAlign: "middle",
                      },
                      "& th:nth-of-type(7), & td:nth-of-type(7)": { px: 2.5 },
                      "& td:nth-of-type(7)": { verticalAlign: "top" },
                    }}
                  >
                    <TableHead>
                      <TableRow>
                        {[
                          ["Created", "13%"],
                          ["Type", "10%"],
                          ["State", "10%"],
                          ["Wait / run", "15%"],
                          ["Total", "11%"],
                          ["Attempts", "7%"],
                          ["Failure", "10%"],
                          ["Workspace", "13%"],
                          ["Job", "11%"],
                        ].map(([label, width]) => (
                          <TableCell
                            key={label}
                            component="th"
                            scope="col"
                            align={
                              label === "State" || label === "Attempts" || label === "Failure"
                                ? "center"
                                : "left"
                            }
                            sx={{ width }}
                          >
                            {label}
                          </TableCell>
                        ))}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {page.map((job) => (
                        <TableRow key={job.job_id}>
                          <TableCell>
                            <Typography variant="body2">
                              Created {timestamp(job.created_at)}
                            </Typography>
                            <AttemptTime job={job} />
                          </TableCell>
                          <TableCell>{title(job.job_type)}</TableCell>
                          <TableCell align="center" sx={{ verticalAlign: "middle" }}>
                            <Status job={job} />
                          </TableCell>
                          <TableCell>
                            <Typography variant="body2">{timing(job)}</Typography>
                            <Typography variant="caption" component="div">
                              <PreviousWait job={job} />
                            </Typography>
                            {job.timing_anomaly && (
                              <Typography variant="caption">
                                Timing adjusted for clock skew.
                              </Typography>
                            )}
                          </TableCell>
                          <TableCell sx={{ whiteSpace: "nowrap" }}>
                            <Typography variant="body2">
                              {duration(job.total_elapsed_seconds)}
                            </Typography>
                          </TableCell>
                          <TableCell align="center">{job.attempts_started}</TableCell>
                          <TableCell
                            align="center"
                            style={{ verticalAlign: job.failure_description ? "top" : "middle" }}
                            sx={{
                              color: job.failure_description ? "error.main" : "text.secondary",
                              minWidth: 85,
                            }}
                          >
                            {job.failure_description ?? "—"}
                          </TableCell>
                          <TableCell>
                            <Identifier
                              id={job.workspace_id}
                              compact
                              kind="Workspace"
                              onWorkspace={onWorkspace}
                              filters={filters}
                            />
                          </TableCell>
                          <TableCell>
                            <Identifier
                              id={job.job_id}
                              compact
                              kind="Job"
                              onWorkspace={onWorkspace}
                              filters={filters}
                            />
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Stack>
            ),
        )}
      </Stack>
    );
  return (
    <Stack sx={{ gap: 2 }}>
      {pages.map(
        (page, index) =>
          page.length > 0 && (
            <Stack key={page[0]?.job_id ?? index} sx={{ gap: 1 }}>
              <Typography variant="body2" color="textSecondary">
                Jobs observed {timestamp(page[0]?.as_of ?? "")}
              </Typography>
              <Stack component="ul" sx={{ gap: 1, p: 0, m: 0 }}>
                {page.map((job) => (
                  <Paper
                    key={job.job_id}
                    component="li"
                    variant="outlined"
                    sx={{ p: 2, listStyle: "none" }}
                  >
                    <Stack
                      direction="row"
                      sx={{ gap: 1, alignItems: "center", flexWrap: "wrap", mb: 1 }}
                    >
                      <Typography variant="h3" component="h3">
                        {title(job.job_type)}
                      </Typography>
                      <Status job={job} />
                    </Stack>
                    <Identifier
                      id={job.job_id}
                      kind="Job"
                      onWorkspace={onWorkspace}
                      filters={filters}
                    />
                    <Box>
                      <Identifier
                        id={job.workspace_id}
                        kind="Workspace"
                        onWorkspace={onWorkspace}
                        filters={filters}
                      />
                    </Box>
                    <Typography>
                      {timing(job)} · Attempts: {job.attempts_started}
                    </Typography>
                    <Typography variant="body2">
                      Total elapsed: {duration(job.total_elapsed_seconds)}
                      {job.attempts_started > 0 && job.status !== "queued" && (
                        <>
                          {" "}
                          · <PreviousWait job={job} />
                        </>
                      )}
                    </Typography>
                    <AttemptTime job={job} />
                    {job.failure_description && (
                      <Typography color="error.main">{job.failure_description}</Typography>
                    )}
                    {job.timing_anomaly && (
                      <Typography color="textSecondary">Timing adjusted for clock skew.</Typography>
                    )}
                    <Typography variant="body2" color="textSecondary">
                      Created {timestamp(job.created_at)}
                    </Typography>
                  </Paper>
                ))}
              </Stack>
            </Stack>
          ),
      )}
    </Stack>
  );
}
