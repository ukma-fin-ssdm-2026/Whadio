import { Button, Chip, CircularProgress, ListItem, ListItemText, Stack } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "@/shared/api/errors";
import { EmptyState } from "@/shared/ui/EmptyState";
import { ErrorBanner } from "@/shared/ui/ErrorBanner";
import { ListPanel } from "@/shared/ui/ListPanel";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { shareQueries, useDecideRequest } from "../api/shares";

const STATUS_LABELS: Record<string, string> = {
  approved: "Approved",
  declined: "Declined",
};

function listError(error: Error) {
  if (error instanceof ApiError && error.code === "INSUFFICIENT_ROLE") {
    return "Only the person who created this share can see its requests.";
  }
  if (error instanceof ApiError && error.status === 404) return "This share does not exist.";
  return error.message;
}

export function AccessRequests({ shareId }: { shareId: string }) {
  const notify = useNotify();
  const requests = useQuery(shareQueries.requests(shareId));
  const decide = useDecideRequest(shareId);

  if (requests.isLoading) return <CircularProgress aria-label="Loading requests" size={24} />;
  if (requests.error) return <ErrorBanner>{listError(requests.error)}</ErrorBanner>;
  if (!requests.data?.length) {
    return (
      <EmptyState
        title="No requests yet"
        hint="Someone who opens the share link and asks for access appears here."
      />
    );
  }

  const answer = (requestId: string, approve: boolean) =>
    decide.mutate(
      { requestId, approve },
      { onSuccess: () => notify(approve ? "Request approved." : "Request declined.") },
    );

  return (
    <Stack sx={{ gap: 2 }}>
      {decide.error && <ErrorBanner>{decide.error.message}</ErrorBanner>}
      <ListPanel label="Access requests">
        {requests.data.map((request) => (
          <ListItem key={request.id} sx={{ gap: 2, py: 1.5, flexWrap: "wrap" }}>
            <ListItemText
              primary={request.name}
              secondary={request.email}
              slotProps={{ primary: { variant: "subtitle1" } }}
              sx={{ overflowWrap: "anywhere", flex: "1 1 12rem" }}
            />
            {request.status === "pending" ? (
              <Stack direction="row" sx={{ gap: 1 }}>
                <Button
                  color="inherit"
                  disabled={decide.isPending}
                  onClick={() => answer(request.id, false)}
                >
                  Decline
                </Button>
                <Button
                  variant="contained"
                  disabled={decide.isPending}
                  onClick={() => answer(request.id, true)}
                >
                  Approve
                </Button>
              </Stack>
            ) : (
              <Chip size="small" label={STATUS_LABELS[request.status] ?? request.status} />
            )}
          </ListItem>
        ))}
      </ListPanel>
    </Stack>
  );
}
