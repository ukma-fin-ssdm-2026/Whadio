export type MeetingLink = {
  meetingId: string;
  revisionId: string | null;
};

export function readMeetingLink(href: string): MeetingLink | null {
  const url = new URL(href);
  const match = url.pathname.match(/\/meetings\/([^/]+)\/?$/);
  const meetingId = match?.[1];
  if (meetingId === undefined) return null;
  return { meetingId, revisionId: url.searchParams.get("revision_id") || null };
}

export function meetingPath(
  href: string,
  meetingId: string,
  revisionId: string | null = null,
): string {
  const url = new URL(href);
  const base = url.pathname.replace(/\/meetings(?:\/[^/]+)?\/?$/, "").replace(/\/$/, "");
  const path = `${base}/meetings/${encodeURIComponent(meetingId)}`;
  return revisionId ? `${path}?${new URLSearchParams({ revision_id: revisionId })}` : path;
}

export function meetingLibraryPath(href: string): string {
  return meetingPath(href, "");
}
