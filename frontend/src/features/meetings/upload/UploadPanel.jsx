import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import {
  Box,
  Button,
  Card,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useState } from "react";
import { titleCase } from "@/shared/lib/format";

export function UploadPanel({ workspace, onUpload }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [file, setFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!file) {
      setError("Select an audio or video file.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await onUpload({ file, name });
      setOpen(false);
      setName("");
      setFile(null);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card className="upload-panel">
      <Stack
        direction={{ xs: "column", sm: "row" }}
        sx={{
          gap: 1.5,
          justifyContent: "space-between",
          alignItems: { xs: "stretch", sm: "center" },
        }}
      >
        <Box>
          <Typography variant="h2" sx={{ fontSize: 18, fontWeight: 650 }}>
            Upload recording
          </Typography>
          <Typography color="textSecondary" sx={{ fontSize: 14 }}>
            Queue audio or video for processing.
          </Typography>
        </Box>
        <Button
          variant="contained"
          startIcon={<CloudUploadOutlinedIcon />}
          onClick={() => setOpen(true)}
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
            <FormControl fullWidth>
              <InputLabel>Note preset</InputLabel>
              <Select label="Note preset" value={workspace.preset} disabled>
                <MenuItem value={workspace.preset}>
                  {titleCase(workspace.preset)} (workspace default)
                </MenuItem>
              </Select>
            </FormControl>
            <Button
              className="file-picker-button"
              component="label"
              variant="outlined"
              startIcon={<CloudUploadOutlinedIcon />}
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
          <Button variant="contained" disabled={submitting} onClick={submit}>
            {submitting ? "Uploading..." : "Queue processing"}
          </Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}
