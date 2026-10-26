import http from "k6/http";
import { check, fail, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://host.docker.internal:3000";
const PAGE_LIMIT = 100;
const REQUEST_TIMEOUT = "4s";

export const options = {
  scenarios: {
    workspace_list: {
      executor: "constant-vus",
      exec: "testWorkspaceList",
      vus: 50,
      duration: "30s",
      gracefulStop: "5s",
    },
    meeting_list: {
      executor: "constant-vus",
      exec: "testMeetingList",
      vus: 50,
      duration: "30s",
      startTime: "35s",
      gracefulStop: "5s",
    },
  },
  thresholds: {
    "http_req_duration{endpoint:workspace-list}": ["p(95)<=200"],
    "http_req_duration{endpoint:meeting-list}": ["p(95)<=200"],
    "http_req_failed{endpoint:workspace-list}": ["rate==0"],
    "http_req_failed{endpoint:meeting-list}": ["rate==0"],
    "checks{endpoint:workspace-list}": ["rate==1"],
    "checks{endpoint:meeting-list}": ["rate==1"],
  },
};

function credentials() {
  if (!__ENV.WHADIO_EMAIL || !__ENV.WHADIO_PASSWORD) {
    fail("Set WHADIO_EMAIL and WHADIO_PASSWORD for a local browser account");
  }
  return {
    email: __ENV.WHADIO_EMAIL,
    password: __ENV.WHADIO_PASSWORD,
    kind: "browser",
  };
}

function sessionParams(session, endpoint) {
  return {
    headers: {
      Cookie: `whadio_session=${session}`,
    },
    tags: { endpoint },
  };
}

function loadRequestParams(session, endpoint) {
  return { ...sessionParams(session, endpoint), timeout: REQUEST_TIMEOUT };
}

function failResponse(label, response) {
  const reason = response.error ? `: ${response.error}` : "";
  fail(`${label} failed with HTTP ${response.status}${reason}`);
}

export function setup() {
  const signIn = http.post(`${BASE_URL}/api/v1/sessions`, JSON.stringify(credentials()), {
    headers: { "Content-Type": "application/json" },
    tags: { setup: "sign-in" },
  });
  if (signIn.status !== 201) {
    failResponse("Sign-in", signIn);
  }

  const session = signIn.cookies.whadio_session?.[0]?.value;
  if (!session) {
    fail("Sign-in response did not set whadio_session");
  }

  const workspaces = http.get(
    `${BASE_URL}/api/v1/workspaces?limit=${PAGE_LIMIT}`,
    sessionParams(session, "setup"),
  );
  if (workspaces.status !== 200) {
    failResponse("Workspace discovery", workspaces);
  }

  const workspaceId = workspaces.json("items.0.id");
  if (typeof workspaceId !== "string" || workspaceId.length === 0) {
    fail("The test account has no workspace");
  }
  return { session, workspaceId };
}

export function testWorkspaceList(data) {
  const endpoint = "workspace-list";
  const response = http.get(
    `${BASE_URL}/api/v1/workspaces?limit=${PAGE_LIMIT}`,
    loadRequestParams(data.session, endpoint),
  );
  check(
    response,
    { "workspace list returns 200": (result) => result.status === 200 },
    { endpoint },
  );
  sleep(1);
}

export function testMeetingList(data) {
  const endpoint = "meeting-list";
  const response = http.get(
    `${BASE_URL}/api/v1/workspaces/${data.workspaceId}/meetings?limit=${PAGE_LIMIT}`,
    loadRequestParams(data.session, endpoint),
  );
  check(
    response,
    { "meeting list returns 200": (result) => result.status === 200 },
    { endpoint },
  );
  sleep(1);
}
