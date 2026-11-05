import { zodResolver } from "@hookform/resolvers/zod";
import {
  Alert,
  Box,
  Button,
  Card,
  Checkbox,
  FormControlLabel,
  Link,
  Typography,
} from "@mui/material";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "@/shared/api/errors";
import type { Schemas } from "@/shared/api/types";
import { FormTextField } from "@/shared/ui/FormTextField";
import { completePasswordReset, completeRegistration } from "../api/account-links";

const PASSWORD_RULE = "Use 12–128 characters, including at least one capital letter and one number";
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
  const schema = z.object({
    name: registration ? z.string().trim().min(1, "Enter your name").max(100) : z.string(),
    password: z.string().refine((value) => {
      const characters = Array.from(value);
      return (
        characters.length >= 12 &&
        characters.length <= 128 &&
        /\p{Uppercase}/u.test(value) &&
        // Python's isdigit accepts more than decimal digits; the server validates the exact set.
        /\p{N}/u.test(value)
      );
    }, PASSWORD_RULE),
    accept_terms: z
      .boolean()
      .refine(
        (value) => !registration || value,
        "Accept the Terms and Conditions to create your account",
      ),
  });
  const { control, handleSubmit, setError, reset, formState } = useForm({
    resolver: zodResolver(schema),
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
        let fieldError = false;
        for (const { field, message } of error.details) {
          if (field === "name" || field === "password" || field === "accept_terms") {
            setError(field, { type: "server", message });
            fieldError = true;
          }
        }
        if (!fieldError) setError("root.server", { message: error.message });
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
            {registration && (
              <>
                <Controller
                  control={control}
                  name="accept_terms"
                  render={({ field }) => (
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={field.value}
                          onChange={(_, checked) => field.onChange(checked)}
                          onBlur={field.onBlur}
                          slotProps={{
                            input: {
                              ref: field.ref,
                              "aria-invalid": Boolean(formState.errors.accept_terms),
                              "aria-describedby": formState.errors.accept_terms
                                ? "terms-error"
                                : undefined,
                            },
                          }}
                          name={field.name}
                        />
                      }
                      label={
                        <>
                          I accept the{" "}
                          <Link href={termsHref} target="_blank" rel="noopener noreferrer">
                            Terms and Conditions
                          </Link>
                        </>
                      }
                    />
                  )}
                />
                {formState.errors.accept_terms && (
                  <Typography id="terms-error" color="error" role="alert">
                    {formState.errors.accept_terms.message}
                  </Typography>
                )}
              </>
            )}
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
