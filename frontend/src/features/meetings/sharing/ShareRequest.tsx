import { Alert, Box, Button, Card, CircularProgress, Stack, Typography } from "@mui/material";
import { useState } from "react";
import { z } from "zod";
import { ApiError } from "@/shared/api/errors";
import type { Schemas } from "@/shared/api/types";
import { requestShareAccess } from "../api/shares";

const validId = z.uuid();

interface ShareRequestProps {
  shareId: string;
  token: string | null;
  currentUser: Schemas["UserRead"] | null | undefined;
  sessionError?: string;
  onRetrySession?: () => void;
  onRequestSignIn: () => void;
  onSessionExpired: () => void;
  onOpen: () => void;
}

type RequestState =
  | { kind: "ready" }
  | { kind: "requested" }
  | { kind: "already-requested" }
  | { kind: "has-access" }
  | { kind: "invalid" };

function ShareCard({ children }: { children: React.ReactNode }) {
  return (
    <Box sx={{ display: "grid", minHeight: "100vh", p: "1.25rem", placeItems: "center" }}>
      <Card sx={{ display: "grid", gap: 2, width: "min(100%, 34rem)", p: { xs: 2, sm: 3 } }}>
        <Typography variant="h3" component="p">
          Whadio
        </Typography>
        {children}
      </Card>
    </Box>
  );
}

export function ShareRequest({
  shareId,
  token,
  currentUser,
  sessionError,
  onRetrySession,
  onRequestSignIn,
  onSessionExpired,
  onOpen,
}: ShareRequestProps) {
  const usable = token !== null && validId.safeParse(shareId).success;
  const [state, setState] = useState<RequestState>({ kind: usable ? "ready" : "invalid" });
  const [requesting, setRequesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (state.kind === "invalid") {
    return (
      <ShareCard>
        <Typography variant="h1">Share link unavailable</Typography>
        <Alert severity="error">
          This share link cannot be used. Ask the person who shared it for a new one.
        </Alert>
      </ShareCard>
    );
  }
  if (state.kind === "requested" || state.kind === "already-requested") {
    return (
      <ShareCard>
        <Typography variant="h1">Access requested</Typography>
        <Alert severity="info">
          {state.kind === "requested"
            ? "The person who shared this meeting has been asked to approve you."
            : "You have already asked for access to this meeting."}{" "}
          Once they approve, it appears under Shared with me.
        </Alert>
      </ShareCard>
    );
  }
  if (state.kind === "has-access") {
    return (
      <ShareCard>
        <Typography variant="h1">You already have access</Typography>
        <Typography color="textSecondary">
          This share is yours, or you can read the meeting in its workspace.
        </Typography>
        <Button variant="contained" onClick={onOpen}>
          Open shared meetings
        </Button>
      </ShareCard>
    );
  }

  const request = async () => {
    if (!token) return;
    setRequesting(true);
    setError(null);
    try {
      await requestShareAccess(shareId, token);
      setState({ kind: "requested" });
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === "LINK_INVALID") {
        setState({ kind: "invalid" });
      } else if (failure instanceof ApiError && failure.code === "ACCESS_REQUEST_EXISTS") {
        setState({ kind: "already-requested" });
      } else if (failure instanceof ApiError && failure.code === "ALREADY_HAS_ACCESS") {
        setState({ kind: "has-access" });
      } else if (failure instanceof ApiError && failure.status === 401) {
        onSessionExpired();
      } else {
        setError(failure instanceof ApiError ? failure.message : "Could not request access.");
      }
    } finally {
      setRequesting(false);
    }
  };

  return (
    <ShareCard>
      <Box>
        <Typography variant="h1">A meeting was shared with you</Typography>
        <Typography color="textSecondary">
          The person who shared it approves who can read it. You will see its transcript and notes
          once they do.
        </Typography>
      </Box>
      {error && <Alert severity="error">{error}</Alert>}
      {currentUser === undefined ? (
        sessionError ? (
          <Stack sx={{ gap: 1 }}>
            <Alert severity="error">{sessionError}</Alert>
            <Button onClick={onRetrySession}>Retry account check</Button>
            <Button variant="contained" onClick={onRequestSignIn}>
              Sign in
            </Button>
          </Stack>
        ) : (
          <CircularProgress size={24} aria-label="Checking your account" />
        )
      ) : currentUser === null ? (
        <Stack sx={{ gap: 1 }}>
          <Typography>Sign in to ask for access.</Typography>
          <Button variant="contained" onClick={onRequestSignIn}>
            Sign in
          </Button>
        </Stack>
      ) : (
        <Stack sx={{ gap: 1 }}>
          <Typography color="textSecondary">Signed in as {currentUser.email}.</Typography>
          <Button variant="contained" loading={requesting} onClick={() => void request()}>
            Request access
          </Button>
        </Stack>
      )}
    </ShareCard>
  );
}
