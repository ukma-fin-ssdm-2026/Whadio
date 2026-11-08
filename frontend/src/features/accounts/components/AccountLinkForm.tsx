import { zodResolver } from "@hookform/resolvers/zod";
import { Alert, Box, Button, Card, Link, Typography } from "@mui/material";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "@/shared/api/errors";
import type { Schemas } from "@/shared/api/types";
import { FormTextField } from "@/shared/ui/FormTextField";
import {
  PASSWORD_RULE,
  registrationSchema,
  showRegistrationError,
  TermsField,
} from "@/shared/ui/RegistrationFields";
import { completePasswordReset, completeRegistration } from "../api/account-links";

const resetSchema = registrationSchema.extend({ name: z.string(), accept_terms: z.boolean() });
const INVALID_LINK = "This link cannot be used. Ask your operator for a new link.";
const validId = z.uuid();

interface Props {
  kind: "registration" | "reset";
  id: string;
  token: string | null;
  termsHref: string;
  signInHref: string;
  onComplete: (user?: Schemas["UserRead"]) => Promise<void>;
}

export function AccountLinkForm({ kind, id, token, termsHref, signInHref, onComplete }: Props) {
  const registration = kind === "registration";
  const [invalid, setInvalid] = useState(false);
  const { control, handleSubmit, setError, reset, formState } = useForm({
    resolver: zodResolver(registration ? registrationSchema : resetSchema),
    defaultValues: { name: "", password: "", accept_terms: false },
  });
  const unusable = invalid || !token || !validId.safeParse(id).success;
  const submit = handleSubmit(async (values) => {
    if (unusable || !token) return;
    try {
      const user = registration
        ? await completeRegistration(id, { ...values, token })
        : await completePasswordReset(id, { token, password: values.password });
      reset();
      await onComplete(user || undefined);
    } catch (error) {
      if (error instanceof ApiError && error.code === "LINK_INVALID") {
        setInvalid(true);
        reset();
      } else if (error instanceof ApiError) {
        showRegistrationError(error, setError);
      } else {
        setError("root.server", { message: "Could not complete this request. Try again." });
      }
    }
  });

  return (
    <Box sx={{ display: "grid", minHeight: "100vh", p: "1.25rem", placeItems: "center" }}>
      <Card
        component="form"
        noValidate
        onSubmit={submit}
        sx={{ display: "grid", gap: "1.1rem", width: "min(100%, 28rem)", p: "1.5rem" }}
      >
        <Typography variant="h3" component="p">
          Whadio
        </Typography>
        <Box>
          <Typography variant="h1">
            {registration ? "Create your account" : "Set a new password"}
          </Typography>
          <Typography color="textSecondary">
            {registration
              ? "Set your name and password to start using Whadio."
              : "Changing your password signs out all browsers and extensions."}
          </Typography>
        </Box>
        {unusable ? (
          <Alert severity="error">{INVALID_LINK}</Alert>
        ) : (
          <>
            {registration && (
              <FormTextField
                control={control}
                name="name"
                label="Name"
                autoComplete="name"
                required
              />
            )}
            <FormTextField
              control={control}
              name="password"
              label="New password"
              type="password"
              autoComplete="new-password"
              helperText={PASSWORD_RULE}
              slotProps={{ formHelperText: { sx: { mx: 0, width: "100%" } } }}
              required
            />
            {registration && <TermsField control={control} termsHref={termsHref} />}
            {formState.errors.root?.server && (
              <Alert severity="error">{formState.errors.root.server.message}</Alert>
            )}
            <Button type="submit" variant="contained" disabled={formState.isSubmitting}>
              {formState.isSubmitting
                ? "Saving..."
                : registration
                  ? "Create account"
                  : "Save new password"}
            </Button>
          </>
        )}
        <Link href={signInHref}>Back to sign in</Link>
      </Card>
    </Box>
  );
}
