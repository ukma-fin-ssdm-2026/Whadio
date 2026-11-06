import WarningAmberOutlinedIcon from "@mui/icons-material/WarningAmberOutlined";
import {
  Box,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { Fragment } from "react";
import type { Schemas } from "@/shared/api/types";
import { formatDuration } from "@/shared/lib/format-duration";

const LONG_WAIT_SECONDS = 15 * 60;
const ROWS = [
  { key: "queued", label: "Queued", helper: "Jobs waiting for a worker." },
  { key: "running", label: "Running", helper: "Jobs currently being processed." },
  { key: "failed", label: "Failed", helper: "Inspect the safe failure reason in the jobs below." },
  {
    key: "unpublished",
    label: "Not yet published",
    helper: "Jobs not yet sent to the worker queue.",
  },
  {
    key: "oldest_queue_wait_seconds",
    label: "Oldest known queue wait",
    helper: "Longest known wait. Warns above 15 minutes.",
  },
  {
    key: "unknown_queue_waits",
    label: "Unknown queue waits",
    helper: "Missing queue-entry times; excluded from oldest wait.",
  },
] as const;

export function CountsTable({ counts }: { counts: Schemas["JobCounts"][] }) {
  return (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small" aria-label="Job counts by type">
        <TableHead>
          <TableRow>
            <TableCell>Retained jobs</TableCell>
            {counts.map((count) => (
              <TableCell key={count.job_type} align="right" component="th" scope="col">
                {count.job_type === "notes" ? "Notes" : "Transcription"}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {ROWS.map(({ key, label, helper }) => (
            <Fragment key={key}>
              <TableRow>
                <TableCell
                  component="th"
                  scope="row"
                  sx={{ width: { xs: "auto", sm: "60%" }, py: 0.75 }}
                >
                  <Typography variant="body2" component="span">
                    {label}
                  </Typography>
                  <Typography
                    variant="caption"
                    color="textSecondary"
                    sx={{ display: { xs: "none", sm: "inline" }, ml: 1 }}
                  >
                    {helper}
                  </Typography>
                </TableCell>
                {counts.map((count) => {
                  const value = count[key];
                  const warning =
                    key === "failed" || key === "unpublished"
                      ? value !== null && value > 0
                      : key === "oldest_queue_wait_seconds" &&
                        count.queued > 0 &&
                        value !== null &&
                        value > LONG_WAIT_SECONDS;
                  const displayed =
                    key === "oldest_queue_wait_seconds"
                      ? count.queued === 0
                        ? "None queued"
                        : value === null
                          ? "Unknown"
                          : formatDuration(Math.floor(value))
                      : value;
                  return (
                    <TableCell
                      key={count.job_type}
                      align="right"
                      sx={{
                        verticalAlign: "top",
                        py: 0.75,
                        fontVariantNumeric: "tabular-nums",
                        color: warning ? "warning.main" : "text.primary",
                      }}
                    >
                      <Box sx={{ display: "inline-flex", gap: 0.5, alignItems: "center" }}>
                        {warning && (
                          <WarningAmberOutlinedIcon
                            fontSize="small"
                            titleAccess={`${label} needs attention`}
                          />
                        )}
                        {displayed}
                      </Box>
                    </TableCell>
                  );
                })}
              </TableRow>
              <TableRow sx={{ display: { xs: "table-row", sm: "none" } }}>
                <TableCell colSpan={counts.length + 1} sx={{ pt: 0, pb: 1 }}>
                  <Typography variant="caption" color="textSecondary">
                    {helper}
                  </Typography>
                </TableCell>
              </TableRow>
            </Fragment>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
