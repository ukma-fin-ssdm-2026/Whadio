import { useQuery } from "@tanstack/react-query";
import { meetingQueries } from "./api/meetings";
import { describeMeetingFigures } from "./model";

export function MeetingFigures({ workspaceId }: { workspaceId: string }) {
  const { data, isError } = useQuery(meetingQueries.latest(workspaceId));
  if (data) return describeMeetingFigures(data);
  return isError ? "Meetings unavailable" : "Loading meetings";
}
