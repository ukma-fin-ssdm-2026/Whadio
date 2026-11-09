import {
  Alert,
  Button,
  Chip,
  CircularProgress,
  ListItem,
  ListItemText,
  Stack,
} from "@mui/material";
import { useInfiniteQuery } from "@tanstack/react-query";
import { formatDate, titleCase } from "@/shared/lib/format";
import { ListPanel } from "@/shared/ui/ListPanel";
import { SectionHeader } from "@/shared/ui/SectionHeader";
import { memberQueries } from "../api/members";

export function MemberPanel({ workspaceId }: { workspaceId: string }) {
  const members = useInfiniteQuery(memberQueries.list(workspaceId));

  return (
    <Stack sx={{ gap: 1.5 }}>
      <SectionHeader title="Members" description="Everyone in this workspace and their role." />
      {members.error && <Alert severity="error">{members.error.message}</Alert>}
      {members.isPending ? (
        <CircularProgress size={24} aria-label="Loading members" />
      ) : members.isLoadingError ? null : (
        <ListPanel label="Workspace members">
          {members.data.map((member) => (
            <ListItem key={member.user_id} sx={{ gap: 2, py: 1.5 }}>
              <ListItemText
                primary={member.name}
                secondary={`${member.email} · Joined ${formatDate(member.joined_at)}`}
                slotProps={{ primary: { variant: "subtitle1" } }}
                sx={{ overflowWrap: "anywhere" }}
              />
              <Chip label={titleCase(member.role)} size="small" variant="outlined" />
            </ListItem>
          ))}
        </ListPanel>
      )}
      {members.hasNextPage && (
        <Button disabled={members.isFetchingNextPage} onClick={() => void members.fetchNextPage()}>
          {members.isFetchingNextPage ? "Loading..." : "Load more members"}
        </Button>
      )}
    </Stack>
  );
}
