import { Button, Typography } from "@mui/material";
import { ApiError } from "@/shared/api/errors";
import { CenteredScreen } from "./CenteredScreen";

const UNREADABLE_FAILURE = "This page could not be loaded.";

export function RouteError({ error }: { error: unknown }) {
  return (
    <CenteredScreen>
      <Typography role="alert">
        {error instanceof ApiError ? error.message : UNREADABLE_FAILURE}
      </Typography>
      <Button variant="outlined" onClick={() => window.location.reload()}>
        Reload
      </Button>
    </CenteredScreen>
  );
}
