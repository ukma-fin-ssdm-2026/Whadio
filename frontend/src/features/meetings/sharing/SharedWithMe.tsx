import {
  Button,
  CircularProgress,
  ListItem,
  ListItemButton,
  ListItemText,
  Stack,
} from "@mui/material";
import { useInfiniteQuery } from "@tanstack/react-query";
import { formatDate } from "@/shared/lib/format";
import { EmptyState } from "@/shared/ui/EmptyState";
import { ErrorBanner } from "@/shared/ui/ErrorBanner";
import { ListPanel } from "@/shared/ui/ListPanel";
import { shareQueries } from "../api/shares";

export function SharedWithMe({ onOpen }: { onOpen: (shareId: string) => void }) {
  const shares = useInfiniteQuery(shareQueries.received());

  if (shares.isLoading) return <CircularProgress aria-label="Loading shared meetings" size={24} />;
  if (shares.error) return <ErrorBanner>{shares.error.message}</ErrorBanner>;
  if (!shares.data?.length) {
    return (
      <EmptyState
        title="Nothing shared with you yet"
        hint="A meeting appears here once the person who shared it approves your request."
      />
    );
  }
  return (
    <Stack sx={{ gap: 2 }}>
      <ListPanel label="Meetings shared with you">
        {shares.data.map((share) => (
          <ListItem key={share.id} disablePadding>
            <ListItemButton onClick={() => onOpen(share.id)}>
              <ListItemText
                primary={`Shared ${formatDate(share.created_at)}`}
                secondary={
                  share.redact_speaker_names ? "Speaker names hidden" : "Speaker names shown"
                }
                slotProps={{ primary: { variant: "subtitle1" } }}
              />
            </ListItemButton>
          </ListItem>
        ))}
      </ListPanel>
      {shares.hasNextPage && (
        <Button
          disabled={shares.isFetchingNextPage}
          onClick={() => shares.fetchNextPage()}
          sx={{ alignSelf: "center" }}
        >
          Show more
        </Button>
      )}
      {shares.isFetchingNextPage && (
        <CircularProgress
          aria-label="Loading more shared meetings"
          size={24}
          sx={{ alignSelf: "center" }}
        />
      )}
    </Stack>
  );
}
