import { zodResolver } from "@hookform/resolvers/zod";
import { Alert, Box, Button, Card, CircularProgress, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "@/shared/api/errors";
import type { Schemas } from "@/shared/api/types";
import { titleCase } from "@/shared/lib/format";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { FormTextField } from "@/shared/ui/FormTextField";
import {
  PASSWORD_RULE,
  registrationSchema,
  showRegistrationError,
  TermsField,
} from "@/shared/ui/RegistrationFields";
import {
  acceptInvitation,
  declineInvitation,
  previewInvitation,
  registerInvitation,
} from "../api/invitations";

const INVALID_LINK = "This invitation link cannot be used. Ask for a new invitation.";
const validId = z.uuid();

type Preview = Schemas["PreviewRead"];
type User = Schemas["UserRead"];

interface InvitationRedemptionProps {
  id: string;
  token: string | null;
  currentUser: User | null | undefined;
  sessionError?: string;
  onRetrySession?: () => void;
  termsHref: string;
  onRequestSignIn: () => void;
  onSessionExpired: () => void;
  onUseDifferentAccount: () => Promise<void>;
  onJoined: (workspaceId: string, user?: User) => Promise<void>;
}

function RegistrationForm({
  id,
  token,
  termsHref,
  onInvalid,
  onAccountExists,
  onJoined,
}: {
  id: string;
  token: string;
  termsHref: string;
  onInvalid: () => void;
  onAccountExists: () => void;
  onJoined: InvitationRedemptionProps["onJoined"];
}) {
  const { control, handleSubmit, setError, formState } = useForm({
    resolver: zodResolver(registrationSchema),
    defaultValues: { name: "", password: "", accept_terms: false },
  });
  const submit = handleSubmit(async (values) => {
    try {
      const registered = await registerInvitation(id, { ...values, token });
      await onJoined(registered.membership.workspace_id, registered.user);
    } catch (error) {
      if (error instanceof ApiError && error.code === "LINK_INVALID") {
        onInvalid();
      } else if (error instanceof ApiError && error.code === "ACCOUNT_EXISTS") {
        onAccountExists();
      } else if (error instanceof ApiError) {
        showRegistrationError(error, setError);
      } else {
        setError("root.server", {
          type: "server",
          message: "Could not create your account. Try again.",
        });
      }
    }
  });

  return (
    <Stack component="form" noValidate onSubmit={submit} sx={{ gap: 1.5 }}>
      <Typography variant="h2">Create your account</Typography>
      <FormTextField control={control} name="name" label="Name" autoComplete="name" required />
      <FormTextField
        control={control}
        name="password"
        label="Password"
        type="password"
        autoComplete="new-password"
        helperText={PASSWORD_RULE}
        slotProps={{ formHelperText: { sx: { mx: 0, width: "100%" } } }}
        required
      />
      <TermsField control={control} termsHref={termsHref} />
      {formState.errors.root?.server && (
        <Alert severity="error">{formState.errors.root.server.message}</Alert>
      )}
      <Button type="submit" variant="contained" loading={formState.isSubmitting}>
        Create account and join
      </Button>
    </Stack>
  );
}

function InvitationCard({ children }: { children: React.ReactNode }) {
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

export function InvitationRedemption({
  id,
  token,
  currentUser,
  sessionError,
  onRetrySession,
  termsHref,
  onRequestSignIn,
  onSessionExpired,
  onUseDifferentAccount,
  onJoined,
}: InvitationRedemptionProps) {
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "ready"; preview: Preview }
    | { kind: "invalid" }
    | { kind: "failed"; message: string }
    | { kind: "declined" }
  >({ kind: "loading" });
  const [accepting, setAccepting] = useState(false);
  const [declineOpen, setDeclineOpen] = useState(false);
  const [declining, setDeclining] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !validId.safeParse(id).success) {
      setState({ kind: "invalid" });
      return;
    }
    const controller = new AbortController();
    let active = true;
    setState({ kind: "loading" });
    void previewInvitation(id, token, controller.signal).then(
      (preview) => {
        if (active) setState({ kind: "ready", preview });
      },
      (error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.code === "LINK_INVALID") {
          setState({ kind: "invalid" });
        } else {
          setState({
            kind: "failed",
            message: error instanceof ApiError ? error.message : "Could not check this invitation.",
          });
        }
      },
    );
    return () => {
      active = false;
      controller.abort();
    };
  }, [id, token]);

  if (state.kind === "loading") {
    return (
      <InvitationCard>
        <CircularProgress aria-label="Checking invitation" sx={{ justifySelf: "center" }} />
      </InvitationCard>
    );
  }
  if (state.kind === "invalid") {
    return (
      <InvitationCard>
        <Typography variant="h1">Invitation unavailable</Typography>
        <Alert severity="error">{INVALID_LINK}</Alert>
      </InvitationCard>
    );
  }
  if (state.kind === "failed") {
    return (
      <InvitationCard>
        <Typography variant="h1">Could not open invitation</Typography>
        <Alert severity="error">{state.message}</Alert>
      </InvitationCard>
    );
  }
  if (state.kind === "declined") {
    return (
      <InvitationCard>
        <Typography variant="h1">Invitation declined</Typography>
        <Alert severity="success">You will not join this workspace.</Alert>
      </InvitationCard>
    );
  }

  const { preview } = state;
  const invalid = () => setState({ kind: "invalid" });
  const accountNowExists = () => {
    setActionError("An account for this invitation already exists. Sign in to accept it.");
    setState({ kind: "ready", preview: { ...preview, account_exists: true } });
  };
  const accept = async () => {
    if (!token) return;
    setAccepting(true);
    setActionError(null);
    try {
      const membership = await acceptInvitation(id, token);
      await onJoined(membership.workspace_id);
    } catch (error) {
      if (error instanceof ApiError && error.code === "LINK_INVALID") {
        invalid();
      } else if (error instanceof ApiError && error.code === "EMAIL_MISMATCH") {
        setActionError(
          "This invitation belongs to a different account. Sign in with the invited address.",
        );
      } else if (error instanceof ApiError && error.status === 401) {
        onSessionExpired();
      } else {
        setActionError(
          error instanceof ApiError ? error.message : "Could not accept the invitation.",
        );
      }
    } finally {
      setAccepting(false);
    }
  };
  const decline = async () => {
    if (!token) return;
    setDeclining(true);
    setActionError(null);
    try {
      await declineInvitation(id, token);
      setDeclineOpen(false);
      setState({ kind: "declined" });
    } catch (error) {
      if (error instanceof ApiError && error.code === "LINK_INVALID") {
        setDeclineOpen(false);
        invalid();
      } else {
        setActionError(
          error instanceof ApiError ? error.message : "Could not decline the invitation.",
        );
      }
    } finally {
      setDeclining(false);
    }
  };

  return (
    <InvitationCard>
      <Box>
        <Typography variant="h1">Join {preview.workspace_name}</Typography>
        <Typography color="textSecondary">
          {preview.email} was invited as a {titleCase(preview.role)}.
        </Typography>
      </Box>
      {actionError && <Alert severity="error">{actionError}</Alert>}
      {preview.account_exists ? (
        currentUser === undefined ? (
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
            <Typography>Sign in with the invited account, then accept the invitation.</Typography>
            <Button variant="contained" onClick={onRequestSignIn}>
              Sign in
            </Button>
          </Stack>
        ) : currentUser.email.toLowerCase() !== preview.email.toLowerCase() ? (
          <Stack sx={{ gap: 1 }}>
            <Alert severity="warning">
              You are signed in with a different account. Use the invited account to continue.
            </Alert>
            <Button variant="contained" onClick={() => void onUseDifferentAccount()}>
              Use a different account
            </Button>
          </Stack>
        ) : (
          <Button variant="contained" loading={accepting} onClick={() => void accept()}>
            Accept invitation
          </Button>
        )
      ) : token ? (
        <RegistrationForm
          id={id}
          token={token}
          termsHref={termsHref}
          onInvalid={invalid}
          onAccountExists={accountNowExists}
          onJoined={onJoined}
        />
      ) : null}
      <Button
        color="inherit"
        onClick={() => {
          setActionError(null);
          setDeclineOpen(true);
        }}
      >
        Decline invitation
      </Button>
      <ConfirmDialog
        open={declineOpen}
        title="Decline this invitation?"
        confirmLabel="Decline invitation"
        destructive
        pending={declining}
        onConfirm={() => void decline()}
        onCancel={() => setDeclineOpen(false)}
      >
        You will not join {preview.workspace_name}.
        {declineOpen && actionError && (
          <Typography component="span" color="error" role="alert" sx={{ display: "block", mt: 1 }}>
            {actionError}
          </Typography>
        )}
      </ConfirmDialog>
    </InvitationCard>
  );
}
