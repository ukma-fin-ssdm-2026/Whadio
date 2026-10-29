import ContentCopyOutlinedIcon from "@mui/icons-material/ContentCopyOutlined";
import DeleteOutlineOutlinedIcon from "@mui/icons-material/DeleteOutlineOutlined";
import KeyOutlinedIcon from "@mui/icons-material/KeyOutlined";
import {
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  ListItem,
  ListItemText,
  MenuItem,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { formatDate } from "@/shared/lib/format";
import { EmptyState } from "@/shared/ui/EmptyState";
import { ListPanel } from "@/shared/ui/ListPanel";
import { SectionHeader } from "@/shared/ui/SectionHeader";
import { SettingsRow } from "@/shared/ui/SettingsRow";

export function McpKeySettings() {
  const [keys, setKeys] = useState([]);
  const [expiresInDays, setExpiresInDays] = useState(30);
  const [secret, setSecret] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const loadKeys = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const page = await api.listMcpKeys();
      setKeys(page.items);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadKeys();
  }, [loadKeys]);

  const createKey = async () => {
    setSubmitting(true);
    setError("");
    try {
      const created = await api.createMcpKey(expiresInDays || null);
      const { secret: createdSecret, ...key } = created;
      setSecret(createdSecret);
      setKeys((current) => [key, ...current]);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSubmitting(false);
    }
  };

  const revokeKey = async (keyId) => {
    setError("");
    try {
      await api.revokeMcpKey(keyId);
      await loadKeys();
    } catch (caught) {
      setError(caught.message);
    }
  };

  return (
    <Stack sx={{ gap: 1.5 }}>
      <SectionHeader
        title="AI assistant access"
        description="Use a personal key to connect an assistant to meetings you can access."
      />
      <SettingsRow
        title="New key"
        description="Choose when the key expires; its secret is shown once."
        control={
          <>
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>Expires</InputLabel>
              <Select
                label="Expires"
                value={expiresInDays}
                onChange={(event) => setExpiresInDays(event.target.value)}
              >
                <MenuItem value="">Never</MenuItem>
                <MenuItem value={30}>30 days</MenuItem>
                <MenuItem value={90}>90 days</MenuItem>
                <MenuItem value={365}>1 year</MenuItem>
              </Select>
            </FormControl>
            <Button
              variant="contained"
              startIcon={<KeyOutlinedIcon />}
              disabled={submitting}
              onClick={createKey}
            >
              {submitting ? "Creating..." : "Create key"}
            </Button>
          </>
        }
      />

      {error && (
        <Typography color="error" role="alert">
          {error}
        </Typography>
      )}
      {loading ? (
        <CircularProgress size={24} />
      ) : keys.length === 0 ? (
        <EmptyState title="No assistant keys yet" />
      ) : (
        <ListPanel>
          {keys.map((key) => (
            <ListItem
              key={key.id}
              secondaryAction={
                key.is_active && (
                  <Tooltip title="Revoke key" arrow>
                    <IconButton
                      edge="end"
                      aria-label="Revoke key"
                      onClick={() => revokeKey(key.id)}
                    >
                      <DeleteOutlineOutlinedIcon />
                    </IconButton>
                  </Tooltip>
                )
              }
              sx={{ gap: 2, py: 1.5 }}
            >
              <KeyOutlinedIcon color={key.is_active ? "primary" : "disabled"} />
              <ListItemText
                primary={`Key ${key.id.slice(0, 8)}`}
                secondary={`Created ${formatDate(key.created_at)} · ${
                  key.expires_at ? `Expires ${formatDate(key.expires_at)}` : "Never expires"
                }`}
                slotProps={{ primary: { variant: "subtitle1" } }}
              />
              <Chip
                size="small"
                label={key.is_active ? "Active" : key.revoked_at ? "Revoked" : "Expired"}
                color={key.is_active ? "success" : "default"}
                variant="outlined"
              />
            </ListItem>
          ))}
        </ListPanel>
      )}

      <Dialog open={Boolean(secret)} onClose={() => setSecret("")} fullWidth maxWidth="sm">
        <DialogTitle>Save your MCP key</DialogTitle>
        <DialogContent>
          <Stack sx={{ gap: 2, pt: 1 }}>
            <Typography color="textSecondary">
              This secret is shown once. Store it securely before closing this window.
            </Typography>
            <TextField
              value={secret}
              slotProps={{
                htmlInput: { readOnly: true, "aria-label": "MCP key secret" },
                input: {
                  endAdornment: (
                    <Tooltip title="Copy key" arrow>
                      <IconButton
                        aria-label="Copy key"
                        onClick={() => navigator.clipboard.writeText(secret)}
                      >
                        <ContentCopyOutlinedIcon />
                      </IconButton>
                    </Tooltip>
                  ),
                },
              }}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button variant="contained" onClick={() => setSecret("")}>
            Done
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
