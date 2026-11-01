import { zodResolver } from "@hookform/resolvers/zod";
import { Box, Button, Card, Typography } from "@mui/material";
import { type UseFormSetError, useForm } from "react-hook-form";
import { z } from "zod";
import type { ApiError } from "@/shared/api/errors";
import type { Schemas } from "@/shared/api/types";
import { FormTextField } from "@/shared/ui/FormTextField";
import { type Credentials, useSignIn } from "../api/session";

const credentials = z.object({
  email: z.string().min(1, "Enter your email address").pipe(z.email("Enter a valid email address")),
  password: z.string().min(1, "Enter your password"),
});

function showServerError(error: ApiError, setError: UseFormSetError<Credentials>) {
  let onField = false;
  for (const { field, message } of error.details) {
    if (field === "email" || field === "password") {
      setError(field, { type: "server", message });
      onField = true;
    }
  }
  if (!onField) setError("root.server", { type: "server", message: error.message });
}

interface SignInFormProps {
  onSignedIn: (user: Schemas["UserRead"]) => void;
  externalError?: string;
}

export function SignInForm({ onSignedIn, externalError }: SignInFormProps) {
  const signIn = useSignIn();
  const { control, handleSubmit, setError, formState } = useForm({
    resolver: zodResolver(credentials),
    defaultValues: { email: "", password: "" },
  });
  const error = formState.errors.root?.server?.message ?? externalError;

  const submit = handleSubmit((values) =>
    signIn.mutate(values, {
      onSuccess: (session) => onSignedIn(session.user),
      onError: (caught) => showServerError(caught, setError),
    }),
  );

  return (
    <Box sx={{ display: "grid", minHeight: "100vh", p: "1.25rem", placeItems: "center" }}>
      <Card
        component="form"
        noValidate
        onSubmit={submit}
        sx={{ display: "grid", gap: "1.1rem", width: "min(100%, 26rem)", p: "1.5rem" }}
      >
        <Typography variant="h3" component="p">
          Whadio
        </Typography>
        <Box>
          <Typography variant="h1">Sign in</Typography>
          <Typography color="textSecondary">Open your meetings, notes, and transcripts.</Typography>
        </Box>
        <FormTextField
          control={control}
          name="email"
          label="Email"
          type="email"
          autoComplete="email"
          required
        />
        <FormTextField
          control={control}
          name="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          required
        />
        {error && (
          <Typography color="error" role="alert">
            {error}
          </Typography>
        )}
        <Button type="submit" variant="contained" disabled={signIn.isPending}>
          {signIn.isPending ? "Signing in..." : "Sign in"}
        </Button>
      </Card>
    </Box>
  );
}
