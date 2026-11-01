import { Stack, Typography } from "@mui/material";
import { TextLink } from "../navigation/links";
import { CenteredScreen } from "./CenteredScreen";

export function NotFoundMessage() {
  return (
    <Stack sx={{ py: 8, gap: 2, alignItems: "center", textAlign: "center" }}>
      <Typography variant="h1">Page not found</Typography>
      <Typography color="textSecondary">This link leads nowhere in Whadio.</Typography>
      <TextLink to="/">Home</TextLink>
    </Stack>
  );
}

export function NotFoundPage() {
  return (
    <CenteredScreen>
      <NotFoundMessage />
    </CenteredScreen>
  );
}
