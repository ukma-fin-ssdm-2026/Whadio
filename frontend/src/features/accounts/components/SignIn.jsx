import { Box, Button, Card, TextField, Typography } from "@mui/material";
import { useState } from "react";

export function SignIn({ onSubmit, externalError }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await onSubmit(email, password);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Box className="auth-screen">
      <Card component="form" className="auth-card" onSubmit={submit}>
        <Typography variant="h3" component="p">
          Whadio
        </Typography>
        <Box>
          <Typography variant="h1">Sign in</Typography>
          <Typography color="textSecondary">Open your meetings, notes, and transcripts.</Typography>
        </Box>
        <TextField
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <TextField
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {(error || externalError) && (
          <Typography color="error" role="alert">
            {error || externalError}
          </Typography>
        )}
        <Button type="submit" variant="contained" disabled={submitting}>
          {submitting ? "Signing in..." : "Sign in"}
        </Button>
      </Card>
    </Box>
  );
}
