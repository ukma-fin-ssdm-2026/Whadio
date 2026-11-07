import { Box, Card, Typography } from "@mui/material";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/terms")({ component: TermsPage });

function TermsPage() {
  return (
    <Box sx={{ display: "grid", minHeight: "100vh", p: "1.25rem", placeItems: "center" }}>
      <Card sx={{ display: "grid", gap: 2, width: "min(100%, 40rem)", p: "1.5rem" }}>
        <Typography variant="h3" component="p">
          Whadio
        </Typography>
        <Typography variant="h1">Terms and Conditions</Typography>
        <Typography>
          By creating an account, you agree to these conditions for using this instance of Whadio.
        </Typography>
        <Typography variant="h2">Recording and consent</Typography>
        <Typography>
          You must obtain the participants’ consent before recording a meeting or uploading a
          recording to Whadio. You are responsible for complying with the rules that apply to your
          meeting.
        </Typography>
        <Typography variant="h2">Sharing meeting content</Typography>
        <Typography>
          Share recordings, transcripts and notes only with people authorised to receive them and
          only with the permissions of the participants and content owners. Do not distribute
          meeting content or access links beyond that audience.
        </Typography>
        <Typography variant="h2">Your instance</Typography>
        <Typography>
          The operator runs this instance and is responsible for its Terms and Conditions. Contact
          your operator with questions about these conditions or your account.
        </Typography>
        <Typography color="textSecondary">
          Return to the registration tab to continue creating your account.
        </Typography>
      </Card>
    </Box>
  );
}
