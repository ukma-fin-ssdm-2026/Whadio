import { useNavigate } from "@tanstack/react-router";

export function useOpenMeeting() {
  const navigate = useNavigate();
  return (meetingId: string) => navigate({ to: "/meetings/$meetingId", params: { meetingId } });
}
