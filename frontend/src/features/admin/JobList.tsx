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
import { useNotify } from "@/shared/ui/NotifyProvider";
import { duration, timestamp, title } from "./format";

type Job = Schemas["JobSnapshot"];
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
  workspaceHref,
  compact = false,
}: {
  id: string;
  kind: "Job" | "Workspace";
  compact?: boolean;
  onWorkspace: (id: string) => void;
  workspaceHref: (id: string) => string;
}) {
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
            href={workspaceHref(id)}
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
  workspaceHref,
}: {
  pages: Job[][];
  onWorkspace: (id: string) => void;
  workspaceHref: (id: string) => string;
}) {
  const desktop = useMediaQuery(useTheme().breakpoints.up("lg"), { noSsr: true });
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
                  <Table size="small" aria-label="Processing jobs">
                    <TableHead>
                      <TableRow>
                        {[
                          "Created",
                          "Type",
                          "State",
                          "Wait / run",
                          "Total",
                          "Attempts",
                          "Failure",
                          "Workspace",
                          "Job",
                        ].map((label) => (
                          <TableCell
                            key={label}
                            component="th"
                            scope="col"
                            align={
                              label === "State" || label === "Attempts" || label === "Failure"
                                ? "center"
                                : "left"
                            }
                            sx={{ px: 0.75 }}
                          >
                            {label}
                          </TableCell>
                        ))}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {page.map((job) => (
                        <TableRow key={job.job_id}>
                          <TableCell sx={{ px: 0.75, verticalAlign: "top" }}>
                            <Typography variant="body2">{timestamp(job.created_at)}</Typography>
                            <AttemptTime job={job} />
                          </TableCell>
                          <TableCell sx={{ px: 0.75, verticalAlign: "top" }}>
                            {title(job.job_type)}
                          </TableCell>
                          <TableCell align="center" sx={{ px: 0.75, verticalAlign: "middle" }}>
                            <Status job={job} />
                          </TableCell>
                          <TableCell sx={{ px: 0.75, verticalAlign: "top" }}>
                            <Typography variant="body2" sx={{ whiteSpace: "nowrap" }}>
                              {timing(job)}
                            </Typography>
                            <Typography
                              variant="caption"
                              component="div"
                              sx={{ whiteSpace: "nowrap" }}
                            >
                              <PreviousWait job={job} />
                            </Typography>
                            {job.timing_anomaly && (
                              <Typography variant="caption">
                                Timing adjusted for clock skew.
                              </Typography>
                            )}
                          </TableCell>
                          <TableCell sx={{ px: 0.75, verticalAlign: "top", whiteSpace: "nowrap" }}>
                            <Typography variant="body2">
                              {duration(job.total_elapsed_seconds)}
                            </Typography>
                          </TableCell>
                          <TableCell align="center" sx={{ px: 0.75, verticalAlign: "top" }}>
                            {job.attempts_started}
                          </TableCell>
                          <TableCell
                            align="center"
                            sx={{
                              color: job.failure_description ? "error.main" : "text.secondary",
                              px: 0.75,
                              verticalAlign: job.failure_description ? "top" : "middle",
                            }}
                          >
                            {job.failure_description ?? "—"}
                          </TableCell>
                          <TableCell sx={{ px: 0.75, verticalAlign: "top" }}>
                            <Identifier
                              id={job.workspace_id}
                              compact
                              kind="Workspace"
                              onWorkspace={onWorkspace}
                              workspaceHref={workspaceHref}
                            />
                          </TableCell>
                          <TableCell sx={{ px: 0.75, verticalAlign: "top" }}>
                            <Identifier
                              id={job.job_id}
                              compact
                              kind="Job"
                              onWorkspace={onWorkspace}
                              workspaceHref={workspaceHref}
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
                      workspaceHref={workspaceHref}
                    />
                    <Box>
                      <Identifier
                        id={job.workspace_id}
                        kind="Workspace"
                        onWorkspace={onWorkspace}
                        workspaceHref={workspaceHref}
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
