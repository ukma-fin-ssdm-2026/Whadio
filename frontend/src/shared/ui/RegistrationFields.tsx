import { Checkbox, FormControlLabel, Link, Typography } from "@mui/material";
import { useId } from "react";
import { type Control, Controller, type UseFormSetError } from "react-hook-form";
import { z } from "zod";
import type { ApiError } from "../api/errors";

export const PASSWORD_RULE =
  "Use 12–128 characters, including at least one capital letter and one number";

export const registrationSchema = z.object({
  name: z.string().trim().min(1, "Enter your name").max(100),
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
    .refine((value) => value, "Accept the Terms and Conditions to create your account"),
});

export type RegistrationValues = z.infer<typeof registrationSchema>;

export function showRegistrationError(
  error: ApiError,
  setError: UseFormSetError<RegistrationValues>,
) {
  let fieldError = false;
  for (const { field, message } of error.details) {
    if (field === "name" || field === "password" || field === "accept_terms") {
      setError(field, { type: "server", message });
      fieldError = true;
    }
  }
  if (!fieldError) setError("root.server", { type: "server", message: error.message });
}

export function TermsField({
  control,
  termsHref,
}: {
  control: Control<RegistrationValues>;
  termsHref: string;
}) {
  const errorId = useId();
  return (
    <Controller
      control={control}
      name="accept_terms"
      render={({ field, fieldState: { error } }) => (
        <>
          <FormControlLabel
            control={
              <Checkbox
                checked={field.value}
                onChange={(_, checked) => field.onChange(checked)}
                onBlur={field.onBlur}
                slotProps={{
                  input: {
                    ref: field.ref,
                    "aria-invalid": Boolean(error),
                    "aria-describedby": error ? errorId : undefined,
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
          {error && (
            <Typography id={errorId} color="error" role="alert">
              {error.message}
            </Typography>
          )}
        </>
      )}
    />
  );
}
