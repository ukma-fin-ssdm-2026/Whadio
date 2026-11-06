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
  useMediaQuery,
  useTheme,
} from "@mui/material";
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

type Metric = (typeof ROWS)[number];

function metricValue(count: Schemas["JobCounts"], key: Metric["key"]) {
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
  return { displayed, warning };
}

function Value({
  displayed,
  warning,
  label,
  outsideWarning = false,
}: ReturnType<typeof metricValue> & { label: string; outsideWarning?: boolean }) {
  return (
    <Box
      component="span"
      sx={{
        display: "inline-flex",
        gap: 0.5,
        alignItems: "center",
        whiteSpace: "nowrap",
        position: outsideWarning ? "relative" : undefined,
      }}
    >
      {warning && (
        <WarningAmberOutlinedIcon
          fontSize="small"
          titleAccess={`${label} needs attention`}
          sx={outsideWarning ? { position: "absolute", right: "calc(100% + 2px)" } : undefined}
        />
      )}
      {displayed}
    </Box>
  );
}

export function CountsTable({ counts }: { counts: Schemas["JobCounts"][] }) {
  const desktop = useMediaQuery(useTheme().breakpoints.up("sm"));
  if (!desktop)
    return (
      <Paper
        component="section"
        variant="outlined"
        aria-label="Job counts by type"
        sx={{ overflow: "hidden" }}
      >
        {ROWS.map(({ key, label, helper }) => (
          <Box
            key={key}
            component="section"
            aria-label={label}
            sx={{ p: 1.5, "& + &": { borderTop: 1, borderColor: "divider" } }}
          >
            <Typography component="h2" variant="body2" sx={{ fontWeight: 600 }}>
              {label}
            </Typography>
            <Typography variant="caption" color="textSecondary" sx={{ display: "block", mt: 0.25 }}>
              {helper}
            </Typography>
            <Box
              component="dl"
              sx={{
                m: 0,
                mt: 1,
                display: "grid",
                gridTemplateColumns: "1fr",
                gap: 0.5,
              }}
            >
              {counts.map((count) => {
                const value = metricValue(count, key);
                return (
                  <Box
                    key={count.job_type}
                    sx={{
                      display: "grid",
                      gridTemplateColumns: "minmax(6rem, 1fr) minmax(8rem, 0.8fr)",
                      alignItems: "center",
                      gap: 1.5,
                    }}
                  >
                    <Typography component="dt" variant="caption" color="textSecondary">
                      {count.job_type === "notes" ? "Notes" : "Transcription"}
                    </Typography>
                    <Typography
                      component="dd"
                      variant="body2"
                      sx={{
                        m: 0,
                        textAlign: "right",
                        paddingInlineEnd: "3.5ch",
                        fontWeight: 400,
                        "& svg": { fontSize: 14 },
                        "& > span": { gap: 0.25 },
                        fontVariantNumeric: "tabular-nums",
                        color: value.warning ? "warning.main" : "text.primary",
                      }}
                    >
                      <Value {...value} label={label} outsideWarning />
                    </Typography>
                  </Box>
                );
              })}
            </Box>
          </Box>
        ))}
      </Paper>
    );
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
            <TableRow key={key}>
              <TableCell component="th" scope="row" sx={{ width: "60%", py: 0.75 }}>
                <Typography variant="body2" component="span">
                  {label}
                </Typography>
                <Typography variant="caption" color="textSecondary" sx={{ ml: 1 }}>
                  {helper}
                </Typography>
              </TableCell>
              {counts.map((count) => {
                const value = metricValue(count, key);
                return (
                  <TableCell
                    key={count.job_type}
                    align="right"
                    sx={{
                      verticalAlign: "top",
                      py: 0.75,
                      fontVariantNumeric: "tabular-nums",
                      color: value.warning ? "warning.main" : "text.primary",
                    }}
                  >
                    <Value {...value} label={label} />
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
