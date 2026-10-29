import DeleteOutlineOutlinedIcon from "@mui/icons-material/DeleteOutlineOutlined";
import KeyOutlinedIcon from "@mui/icons-material/KeyOutlined";
import {
  Button,
  Chip,
  CircularProgress,
  IconButton,
  ListItem,
  ListItemText,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { formatDate } from "@/shared/lib/format";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { EmptyState } from "@/shared/ui/EmptyState";
import { ListPanel } from "@/shared/ui/ListPanel";
import { SectionHeader } from "@/shared/ui/SectionHeader";
import { SettingsRow } from "@/shared/ui/SettingsRow";
import { type McpKey, mcpKeyQueries, useCreateMcpKey, useRevokeMcpKey } from "../api/mcp-keys";
import { McpKeySecretDialog } from "./McpKeySecretDialog";

const NEVER = "never";

const EXPIRY_OPTIONS = [
  { value: NEVER, label: "Never" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "365", label: "1 year" },
];

const shortId = (key: McpKey) => key.id.slice(0, 8);

const keyStatus = (key: McpKey) =>
  key.is_active ? "Active" : key.revoked_at ? "Revoked" : "Expired";

export function McpKeyPanel() {
  const keys = useQuery(mcpKeyQueries.list());
  const createKey = useCreateMcpKey();
  const revokeKey = useRevokeMcpKey();
  const [expiry, setExpiry] = useState("30");
  const [keyToRevoke, setKeyToRevoke] = useState<McpKey | null>(null);
  const error = keys.error ?? createKey.error ?? revokeKey.error;

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
            <TextField
              select
              size="small"
              label="Expires"
              value={expiry}
              onChange={(event) => setExpiry(event.target.value)}
              sx={{ minWidth: 140 }}
            >
              {EXPIRY_OPTIONS.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </TextField>
            <Button
              variant="contained"
              startIcon={<KeyOutlinedIcon />}
              disabled={createKey.isPending}
              onClick={() => createKey.mutate(expiry === NEVER ? null : Number(expiry))}
            >
              {createKey.isPending ? "Creating..." : "Create key"}
            </Button>
          </>
        }
      />

      {error && (
        <Typography color="error" role="alert">
          {error.message}
        </Typography>
      )}
      {keys.isPending ? (
        <CircularProgress size={24} />
      ) : !keys.data?.items.length ? (
        <EmptyState title="No assistant keys yet" />
      ) : (
        <ListPanel>
          {keys.data.items.map((key) => (
            <ListItem
              key={key.id}
              secondaryAction={
                key.is_active && (
                  <Tooltip title="Revoke key" arrow>
                    <IconButton
                      edge="end"
                      aria-label="Revoke key"
                      onClick={() => setKeyToRevoke(key)}
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
                primary={`Key ${shortId(key)}`}
                secondary={`Created ${formatDate(key.created_at)} · ${
                  key.expires_at ? `Expires ${formatDate(key.expires_at)}` : "Never expires"
                }`}
                slotProps={{ primary: { variant: "subtitle1" } }}
              />
              <Chip
                size="small"
                label={keyStatus(key)}
                color={key.is_active ? "success" : "default"}
                variant="outlined"
              />
            </ListItem>
          ))}
        </ListPanel>
      )}

      {keyToRevoke && (
        <ConfirmDialog
          open
          title="Revoke this key?"
          confirmLabel="Revoke"
          destructive
          pending={revokeKey.isPending}
          onConfirm={() =>
            revokeKey.mutate(keyToRevoke.id, { onSettled: () => setKeyToRevoke(null) })
          }
          onCancel={() => setKeyToRevoke(null)}
        >
          {`Assistants that use key ${shortId(keyToRevoke)} lose access at once. This cannot be undone.`}
        </ConfirmDialog>
      )}
      <McpKeySecretDialog secret={createKey.data?.secret} onClose={() => createKey.reset()} />
    </Stack>
  );
}
