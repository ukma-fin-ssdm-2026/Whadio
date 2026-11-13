import { CircularProgress, ListItem, ListItemButton, ListItemText } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { EmptyState } from "@/shared/ui/EmptyState";
import { ErrorBanner } from "@/shared/ui/ErrorBanner";
import { ListPanel } from "@/shared/ui/ListPanel";
import { shareQueries } from "../api/shares";

export function SharedWithMe({ onOpen }: { onOpen: (shareId: string) => void }) {
  const shares = useQuery(shareQueries.received());

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
    <ListPanel label="Meetings shared with you">
      {shares.data.map((share, index) => (
        <ListItem key={share.id} disablePadding>
          <ListItemButton onClick={() => onOpen(share.id)}>
            <ListItemText
              primary={`Shared meeting ${index + 1}`}
              secondary={
                share.redact_speaker_names ? "Speaker names hidden" : "Speaker names shown"
              }
              slotProps={{ primary: { variant: "subtitle1" } }}
            />
          </ListItemButton>
        </ListItem>
      ))}
    </ListPanel>
  );
}
