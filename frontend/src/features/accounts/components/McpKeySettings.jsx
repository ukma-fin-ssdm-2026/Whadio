import ContentCopyOutlinedIcon from "@mui/icons-material/ContentCopyOutlined";
import DeleteOutlineOutlinedIcon from "@mui/icons-material/DeleteOutlineOutlined";
import KeyOutlinedIcon from "@mui/icons-material/KeyOutlined";
import {
  Box,
  Button,
  Card,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
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
    <Stack className="settings-options" sx={{ gap: 1.25 }}>
      <Box>
        <Typography variant="h2" sx={{ fontSize: 24 }}>
          AI assistant access
        </Typography>
        <Typography color="textSecondary">
          Use a personal key to connect an assistant to meetings you can access.
        </Typography>
      </Box>

      <Card className="settings-option-card">
        <Stack
          direction={{ xs: "column", sm: "row" }}
          sx={{ alignItems: { sm: "center" }, gap: 1.25 }}
        >
          <FormControl size="small" sx={{ minWidth: 180 }}>
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
        </Stack>
      </Card>

      {error && (
        <Typography color="error" role="alert">
          {error}
        </Typography>
      )}
      {loading ? (
        <CircularProgress size={24} />
      ) : (
        <Stack sx={{ gap: 1 }}>
          {keys.length === 0 && (
            <Typography color="textSecondary">No assistant keys yet.</Typography>
          )}
          {keys.map((key) => (
            <Box className="mcp-key-row" key={key.id}>
              <KeyOutlinedIcon color={key.is_active ? "primary" : "disabled"} />
              <Box sx={{ minWidth: 0 }}>
                <Typography sx={{ fontWeight: 600 }}>Key {key.id.slice(0, 8)}</Typography>
                <Typography color="textSecondary" sx={{ fontSize: 14 }}>
                  Created {formatDate(key.created_at)} ·{" "}
                  {key.expires_at ? `Expires ${formatDate(key.expires_at)}` : "Never expires"}
                </Typography>
              </Box>
              <Chip
                size="small"
                label={key.is_active ? "Active" : key.revoked_at ? "Revoked" : "Expired"}
                color={key.is_active ? "success" : "default"}
                variant="outlined"
              />
              {key.is_active && (
                <Tooltip title="Revoke key" arrow>
                  <IconButton aria-label="Revoke key" onClick={() => revokeKey(key.id)}>
                    <DeleteOutlineOutlinedIcon />
                  </IconButton>
                </Tooltip>
              )}
            </Box>
          ))}
        </Stack>
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
