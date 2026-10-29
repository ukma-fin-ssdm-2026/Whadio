import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Typography,
} from "@mui/material";
import { CopyField } from "@/shared/ui/CopyField";

interface McpKeySecretDialogProps {
  secret: string | undefined;
  onClose: () => void;
}

export function McpKeySecretDialog({ secret, onClose }: McpKeySecretDialogProps) {
  return (
    <Dialog open={secret !== undefined} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Save your MCP key</DialogTitle>
      <DialogContent>
        <Stack sx={{ gap: 2, pt: 1 }}>
          <Typography color="textSecondary">
            This secret is shown once. Store it securely before closing this window.
          </Typography>
          <CopyField value={secret ?? ""} label="MCP key secret" copyLabel="Copy key" />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button variant="contained" onClick={onClose}>
          Done
        </Button>
      </DialogActions>
    </Dialog>
  );
}
