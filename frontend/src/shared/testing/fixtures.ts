import type { Schemas } from "../api/types";

const CREATED_AT = "2026-10-25T10:00:00Z";

export function errorBody(code: Schemas["ErrorCode"], message: string) {
  return { error: { code, message, details: [], request_id: "request" } };
}

export function workspaceSummary(
  changes: Partial<Schemas["WorkspaceSummary"]> = {},
): Schemas["WorkspaceSummary"] {
  return {
    id: "workspace",
    name: "Demo Workspace",
    is_personal: false,
    my_role: "owner",
    member_count: 2,
    notes_provider: "whadio",
    created_at: CREATED_AT,
    ...changes,
  };
}

export function workspaceRead(
  changes: Partial<Schemas["WorkspaceRead"]> = {},
): Schemas["WorkspaceRead"] {
  return { ...workspaceSummary(), default_preset: "summary", ...changes };
}

export function meetingSummary(
  changes: Partial<Schemas["MeetingSummary"]> = {},
): Schemas["MeetingSummary"] {
  return {
    id: "meeting",
    workspace_id: "workspace",
    folder_id: "folder",
    name: "Weekly sync",
    name_is_generated: false,
    recorded_at: CREATED_AT,
    processing_state: "processed",
    recording_status: "complete",
    source_type: "extension",
    duration_seconds: 5,
    access_mode: "workspace",
    ...changes,
  };
}

export function meetingRead(changes: Partial<Schemas["MeetingRead"]> = {}): Schemas["MeetingRead"] {
  return {
    ...meetingSummary(),
    created_by_user_id: "member",
    created_at: CREATED_AT,
    failure_reason: null,
    is_edited: false,
    recording_available: false,
    recording_delete_after: "2027-10-25T10:00:00Z",
    consent_confirmed_at: null,
    ...changes,
  };
}

export function page<T>(items: T[], nextCursor: string | null = null) {
  return {
    items,
    pagination: { limit: 100, next_cursor: nextCursor, has_more: nextCursor !== null },
  };
}
