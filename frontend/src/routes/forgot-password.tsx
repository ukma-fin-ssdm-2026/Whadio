import { Alert, Box, Card, CircularProgress, Typography } from "@mui/material";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { z } from "zod";
import { TextLink } from "@/app/navigation/links";
import { safeRedirectSearch } from "@/app/navigation/return-to";
import { instanceQuery } from "@/features/accounts/api/instance";
import { PasswordResetRequestForm } from "@/features/accounts/components/PasswordResetRequestForm";

export const Route = createFileRoute("/forgot-password")({
  validateSearch: z.object({ redirect: z.string().optional().catch(undefined) }),
  component: ForgotPasswordRoute,
});

function ForgotPasswordRoute() {
  const queryClient = useQueryClient();
  const { data: instance, isPending } = useQuery(instanceQuery());
  const { redirect } = Route.useSearch();
  const [confirmation, setConfirmation] = useState<string>();

  return (
    <Box sx={{ display: "grid", minHeight: "100vh", p: "1.25rem", placeItems: "center" }}>
      <Card sx={{ display: "grid", gap: "1.1rem", width: "min(100%, 28rem)", p: "1.5rem" }}>
        <Typography variant="h3" component="p">
          Whadio
        </Typography>
        <Typography variant="h1">Reset your password</Typography>
        {confirmation !== undefined ? (
          <Alert severity="success">{confirmation}</Alert>
        ) : instance?.registration_mode === "verified" ? (
          <PasswordResetRequestForm
            onAccepted={setConfirmation}
            onInviteOnly={() => {
              queryClient.setQueryData(instanceQuery().queryKey, {
                ...instance,
                registration_mode: "invite-only",
              });
            }}
          />
        ) : instance?.registration_mode === "invite-only" ? (
          <Alert severity="info">Ask your instance operator for a password reset link.</Alert>
        ) : isPending ? (
          <CircularProgress size={24} aria-label="Checking if password reset is available" />
        ) : (
          <Alert severity="error">Could not check if password reset is available.</Alert>
        )}
        <TextLink to="/sign-in" search={safeRedirectSearch(redirect)} sx={{ justifySelf: "start" }}>
          Back to sign in
        </TextLink>
      </Card>
    </Box>
  );
}
