// The Whadio server the extension signs in to. The token is an extension session: it works only on
// the capture endpoints and for signing out, and it ends after 24 hours. It is kept in session storage,
// which content scripts cannot read, at the cost of signing in again after the browser restarts.

export class ServerError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function failure(response) {
  const body = await response.json().catch(() => null);
  return new ServerError(response.status, body?.error?.message ?? `The server answered ${response.status}`);
}

export async function api(method, path, body) {
  const { server } = await chrome.storage.local.get("server");
  const { token } = await chrome.storage.session.get("token");
  const init = { method, headers: { Authorization: `Bearer ${token}` } };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`${server}/api/v1${path}`, init);
  if (response.status === 401) {
    await chrome.storage.session.remove(["token", "expiresAt", "name"]);
  }
  if (!response.ok) {
    throw await failure(response);
  }
  return response.status === 204 ? null : response.json();
}

// Passwords travel only over HTTPS; plain HTTP is allowed for a server on this computer.
export function insecureServer(server) {
  const url = new URL(server);
  return url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname));
}

// Chrome's match patterns cover every port of a host, so the pattern leaves the port out.
export function originPattern(server) {
  const url = new URL(server);
  return `${url.protocol}//${url.hostname}/*`;
}

export async function signedIn() {
  const { token, expiresAt } = await chrome.storage.session.get(["token", "expiresAt"]);
  return Boolean(token) && Date.parse(expiresAt) > Date.now();
}

export async function signIn(server, email, password) {
  const response = await fetch(`${server}/api/v1/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, kind: "extension" }),
  });
  if (!response.ok) {
    throw await failure(response);
  }
  const session = await response.json();
  await chrome.storage.local.set({ server });
  await chrome.storage.session.set({ token: session.token, expiresAt: session.expires_at, name: session.user.name });
}

export async function signOut() {
  await api("DELETE", "/sessions/current").catch(() => {});
  await chrome.storage.session.remove(["token", "expiresAt", "name"]);
  await chrome.storage.local.remove("destination");
}
