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

export function page<T>(items: T[], nextCursor: string | null = null) {
  return {
    items,
    pagination: { limit: 100, next_cursor: nextCursor, has_more: nextCursor !== null },
  };
}
