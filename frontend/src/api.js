const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...options,
  });

  if (!response.ok) {
    let body;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    const detail = body?.error ?? body?.detail ?? body;
    const message = detail?.message ?? `Request failed (${response.status})`;
    throw new ApiError(message, response.status, detail?.code);
  }

  if (response.status === 204) return null;
  return response.json();
}

export const api = {
  signIn(email, password) {
    return request("/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, kind: "browser" }),
    });
  },

  signOut() {
    return request("/sessions/current", { method: "DELETE" });
  },

  listWorkspaces() {
    return request("/workspaces?limit=100");
  },

  getWorkspace(workspaceId) {
    return request(`/workspaces/${workspaceId}`);
  },

  updateWorkspace(workspaceId, changes) {
    return request(`/workspaces/${workspaceId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
  },

  listMeetings(workspaceId) {
    return request(`/workspaces/${workspaceId}/meetings?limit=100`);
  },

  getMeeting(meetingId) {
    return request(`/meetings/${meetingId}`);
  },

  getTranscript(meetingId) {
    return request(`/meetings/${meetingId}/transcript`);
  },

  listNotes(meetingId) {
    return request(`/meetings/${meetingId}/notes?limit=100`);
  },

  getRecording(meetingId) {
    return request(`/meetings/${meetingId}/recording`);
  },

  uploadMeeting(workspaceId, { file, name }) {
    const body = new FormData();
    body.append("file", file);
    if (name.trim()) body.append("name", name.trim());
    return request(`/workspaces/${workspaceId}/meetings`, {
      method: "POST",
      body,
    });
  },

  listMcpKeys() {
    return request("/users/me/mcp-keys?limit=100");
  },

  createMcpKey(expiresInDays) {
    return request("/users/me/mcp-keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expires_in_days: expiresInDays }),
    });
  },

  revokeMcpKey(keyId) {
    return request(`/users/me/mcp-keys/${keyId}`, { method: "DELETE" });
  },
};
