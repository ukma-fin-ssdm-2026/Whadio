import { zodResolver } from "@hookform/resolvers/zod";
import { Alert, Box, Button, Typography } from "@mui/material";
import { type FormEvent, useRef } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "@/shared/api/errors";
import { FormTextField } from "@/shared/ui/FormTextField";
import { requestPasswordReset } from "../api/account-links";

const requestSchema = z.object({
  email: z
    .string()
    .trim()
    .min(1, "Enter your email address")
    .max(254, "Enter an email address with at most 254 characters")
    // The API validates the full address, including account names with punctuation or Unicode.
    .refine((email) => /^.+@.+$/.test(email), "Enter a valid email address"),
});

interface PasswordResetRequestFormProps {
  onAccepted: (message: string) => void;
  onInviteOnly: () => void;
}

export function PasswordResetRequestForm({
  onAccepted,
  onInviteOnly,
}: PasswordResetRequestFormProps) {
  const submitting = useRef(false);
  const { control, handleSubmit, setError, formState } = useForm({
    resolver: zodResolver(requestSchema),
    defaultValues: { email: "" },
  });

  const send = handleSubmit(async (request) => {
    try {
      const { message } = await requestPasswordReset(request);
      onAccepted(message);
    } catch (error) {
      if (error instanceof ApiError && error.code === "INVITE_ONLY_INSTANCE") {
        onInviteOnly();
        return;
      }
      if (error instanceof ApiError && error.code === "VALIDATION_ERROR") {
        const emailError = error.details.find(({ field }) => field === "email");
        if (emailError) {
          setError("email", { message: emailError.message });
          return;
        }
      }
      setError("root.server", { message: "Could not request a reset link. Try again." });
    }
  });

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    submitting.current = true;
    try {
      await send(event);
    } finally {
      submitting.current = false;
    }
  }

  return (
    <Box component="form" noValidate onSubmit={submit} sx={{ display: "grid", gap: "1.1rem" }}>
      <Typography color="textSecondary">
        Enter your email address to request a reset link.
      </Typography>
      <FormTextField
        control={control}
        name="email"
        label="Email"
        type="email"
        autoComplete="email"
        disabled={formState.isSubmitting}
        slotProps={{ formHelperText: { role: "alert" } }}
        required
      />
      {formState.errors.root?.server && (
        <Alert severity="error">{formState.errors.root.server.message}</Alert>
      )}
      <Button type="submit" variant="contained" disabled={formState.isSubmitting}>
        {formState.isSubmitting ? "Sending..." : "Send reset link"}
      </Button>
    </Box>
  );
}
