import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import {
  Box,
  Button,
  Card,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { type ReactNode, useState } from "react";
import { useUploadMeeting } from "../api/meetings";

interface UploadPanelProps {
  workspaceId: string;
  presetField: ReactNode;
  onUploaded: (meetingId: string) => void;
}

export function UploadPanel({ workspaceId, presetField, onUploaded }: UploadPanelProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileMissing, setFileMissing] = useState(false);
  const upload = useUploadMeeting(workspaceId);
  const error = fileMissing ? "Select an audio or video file." : upload.error?.message;

  const submit = () => {
    setFileMissing(!file);
    if (!file) return;
    upload.mutate(
      { file, name },
      {
        onSuccess: (meeting) => {
          setOpen(false);
          setName("");
          setFile(null);
          onUploaded(meeting.id);
        },
      },
    );
  };

  return (
    <Card
      sx={{
        p: "0.75rem 0.9rem",
        bgcolor: "background.subtle",
        // Paper's dark-scheme overlay would otherwise lighten the colour.
        backgroundImage: "none",
      }}
    >
      <Stack
        direction={{ xs: "column", sm: "row" }}
        sx={{
          gap: 1.5,
          justifyContent: "space-between",
          alignItems: { xs: "stretch", sm: "center" },
        }}
      >
        <Box>
          <Typography variant="h4" component="h2">
            Upload recording
          </Typography>
          <Typography variant="body2" color="textSecondary">
            Queue audio or video for processing.
          </Typography>
        </Box>
        <Button
          variant="contained"
          startIcon={<CloudUploadOutlinedIcon />}
          onClick={() => setOpen(true)}
          sx={{ minHeight: "2.25rem", p: "0.45rem 0.8rem" }}
        >
          Upload
        </Button>
      </Stack>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Upload recording</DialogTitle>
        <DialogContent>
          <Stack sx={{ gap: 2, pt: 0.5 }}>
            <TextField
              label="Meeting name"
              placeholder="Lab 3 architecture planning"
              value={name}
              onChange={(event) => setName(event.target.value)}
              fullWidth
            />
            {presetField}
            <Button
              component="label"
              variant="outlined"
              startIcon={<CloudUploadOutlinedIcon />}
              sx={{ minHeight: "3.25rem", borderStyle: "dashed", bgcolor: "background.subtle" }}
            >
              {file?.name ?? "Select file"}
              <input
                hidden
                type="file"
                accept="audio/*,video/*"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </Button>
            {error && (
              <Typography color="error" role="alert">
                {error}
              </Typography>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" disabled={upload.isPending} onClick={submit}>
            {upload.isPending ? "Uploading..." : "Queue processing"}
          </Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}
