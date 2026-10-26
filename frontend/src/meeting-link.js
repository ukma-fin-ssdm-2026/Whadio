export function readMeetingLink(href) {
  const url = new URL(href);
  const match = url.pathname.match(/\/meetings\/([^/]+)\/?$/);
  if (!match) return null;
  return { meetingId: match[1], revisionId: url.searchParams.get("revision_id") };
}

export function meetingPath(href, meetingId, revisionId = null) {
  const url = new URL(href);
  const base = url.pathname.replace(/\/meetings(?:\/[^/]+)?\/?$/, "").replace(/\/$/, "");
  const path = `${base}/meetings/${encodeURIComponent(meetingId)}`;
  return revisionId ? `${path}?${new URLSearchParams({ revision_id: revisionId })}` : path;
}

export function meetingLibraryPath(href) {
  return meetingPath(href, "");
}
