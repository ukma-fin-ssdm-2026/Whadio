import { act, render, screen, waitFor } from "@testing-library/react";
import { type UserEvent, userEvent } from "@testing-library/user-event";
import { HttpResponse, type HttpResponseResolver, http, type JsonBodyType } from "msw";
import { afterEach, describe, expect, test, vi } from "vitest";
import { POLL_INTERVAL_MS } from "@/features/meetings/api/meetings";
import type { Schemas } from "@/shared/api/types";
import { errorBody, meetingRead, meetingSummary, noteRead, page } from "@/shared/testing/fixtures";
import { server } from "@/shared/testing/server";
import { App } from "./App";

const DEEP_LINK = "/whadio/meetings/meeting?revision_id=original";
const CURRENT_LINK = "/whadio/meetings/meeting";
const ORIGINAL_WORDING = "Original uncorrected wording";
const CURRENT_WORDING = "Current corrected wording";
const LINKED_TITLE = "Linked meeting outside the first page";
const IN_PROGRESS = ["recording", "queued", "processing"] as const;
const FAILURE_REASON = "The recording has no audio";
const GENERATED_NOTES = "Decisions from the weekly sync";

type ApiTraffic = { requests: string[]; signIns: unknown[] };

afterEach(() => {
  vi.useRealTimers();
});

function transcript(original: boolean) {
  return {
    revision: {
      id: original ? "original" : "edited",
      revision_type: original ? "original" : "edited",
    },
    original_revision_id: "original",
    is_edited: true,
    speakers: [{ id: "speaker", display_name: "Demo speaker" }],
    segments: [
      {
        id: "segment",
        speaker_id: "speaker",
        start_seconds: 0,
        end_seconds: 5,
        text: original ? ORIGINAL_WORDING : CURRENT_WORDING,
      },
    ],
  };
}

function serveApi(signedIn: boolean): ApiTraffic {
  let authenticated = signedIn;
  const traffic: ApiTraffic = { requests: [], signIns: [] };
  const member = (body: (url: URL) => JsonBodyType): HttpResponseResolver => {
    return ({ request }) =>
      authenticated
        ? HttpResponse.json(body(new URL(request.url)))
        : HttpResponse.json(
            { error: { code: "UNAUTHENTICATED", message: "Sign in required" } },
            { status: 401 },
          );
  };
  server.use(
    http.all("*", ({ request }) => {
      const url = new URL(request.url);
      traffic.requests.push(`${request.method} ${url.pathname}${url.search}`);
    }),
    http.post("/api/v1/sessions", async ({ request }) => {
      traffic.signIns.push(await request.json());
      authenticated = true;
      return HttpResponse.json({
        user: { id: "member", email: "member@example.com", name: "Demo Member" },
      });
    }),
    http.get(
      "/api/v1/workspaces",
      member(() => ({
        items: [
          {
            id: "workspace",
            name: "Demo Workspace",
            my_role: "Owner",
            member_count: 1,
            notes_provider: "Whadio",
          },
        ],
      })),
    ),
    http.get(
      "/api/v1/workspaces/workspace",
      member(() => ({ default_preset: "summary" })),
    ),
    http.get(
      "/api/v1/workspaces/workspace/meetings",
      member(() => page([])),
    ),
    http.get(
      "/api/v1/meetings/meeting",
      member(() => ({
        id: "meeting",
        workspace_id: "workspace",
        name: LINKED_TITLE,
        recorded_at: "2026-10-25T10:00:00Z",
        processing_state: "processed",
        duration_seconds: 5,
        source_type: "upload",
      })),
    ),
    http.get(
      "/api/v1/meetings/meeting/notes",
      member(() => ({ items: [] })),
    ),
    http.get(
      "/api/v1/meetings/meeting/transcript",
      member((url) => transcript(url.searchParams.get("revision_id") === "original")),
    ),
  );
  return traffic;
}

async function renderSignedOut() {
  window.history.replaceState(null, "", DEEP_LINK);
  sessionStorage.clear();
  const traffic = serveApi(false);
  render(<App />);
  await screen.findByLabelText(/^Email/);
  return traffic;
}

async function openDeepLink(signedIn: boolean) {
  window.history.replaceState(null, "", DEEP_LINK);
  sessionStorage.clear();
  const traffic = serveApi(signedIn);
  const user = userEvent.setup();
  render(<App />);
  if (!signedIn) {
    await user.type(await screen.findByLabelText(/^Email/), "member@example.com");
    await user.type(screen.getByLabelText(/^Password/), "test-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
  }
  await screen.findByText(ORIGINAL_WORDING);
  return { traffic, user };
}

async function showRevision(user: UserEvent, button: string, wording: string) {
  await user.click(screen.getByRole("button", { name: button }));
  await screen.findByText(wording);
}

async function goBackToCurrent(signedIn: boolean) {
  const { user } = await openDeepLink(signedIn);
  await showRevision(user, "View current transcript", CURRENT_WORDING);
  await showRevision(user, "View original transcript", ORIGINAL_WORDING);
  window.history.back();
  await screen.findByText(CURRENT_WORDING);
}

function startSession(path = "/whadio/") {
  window.history.replaceState(null, "", path);
  sessionStorage.clear();
  return serveApi(true);
}

function renderHome() {
  const traffic = startSession();
  render(<App />);
  return traffic;
}

const currentPath = () => window.location.pathname + window.location.search;

describe("signed-out original deep link", () => {
  test("asks to sign in", async () => {
    // Act
    await renderSignedOut();

    // Assert
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  test("withholds the transcript wording", async () => {
    // Act
    await renderSignedOut();

    // Assert
    expect(screen.queryByText(ORIGINAL_WORDING)).not.toBeInTheDocument();
  });

  test("requests no transcript before sign-in", async () => {
    // Act
    const traffic = await renderSignedOut();

    // Assert
    expect(traffic.requests.filter((request) => request.includes("/transcript"))).toEqual([]);
  });

  test("keeps the revision in the URL", async () => {
    // Act
    await renderSignedOut();

    // Assert
    expect(window.location.search).toBe("?revision_id=original");
  });

  test("signs in with the entered browser credentials", async () => {
    // Act
    const { traffic } = await openDeepLink(false);

    // Assert
    expect(traffic.signIns).toEqual([
      { email: "member@example.com", password: "test-password", kind: "browser" },
    ]);
  });
});

describe.for([
  ["an existing session", true],
  ["sign-in", false],
] as const)("original deep link after %s", ([, signedIn]) => {
  test("keeps the original revision in the URL", async () => {
    // Act
    await openDeepLink(signedIn);

    // Assert
    expect(currentPath()).toBe(DEEP_LINK);
  });

  test("requests the original transcript", async () => {
    // Act
    const { traffic } = await openDeepLink(signedIn);

    // Assert
    expect(traffic.requests).toContain(
      "GET /api/v1/meetings/meeting/transcript?revision_id=original",
    );
  });

  test("shows no current wording", async () => {
    // Act
    await openDeepLink(signedIn);

    // Assert
    expect(screen.queryByText(CURRENT_WORDING)).not.toBeInTheDocument();
  });

  test("opens the Transcript tab", async () => {
    // Act
    await openDeepLink(signedIn);

    // Assert
    expect(screen.getByRole("tab", { selected: true })).toHaveTextContent(/^Transcript$/);
  });

  test("switching to the current transcript drops the revision from the URL", async () => {
    // Arrange
    const { user } = await openDeepLink(signedIn);

    // Act
    await showRevision(user, "View current transcript", CURRENT_WORDING);

    // Assert
    expect(currentPath()).toBe(CURRENT_LINK);
  });

  test("switching to the current transcript requests it", async () => {
    // Arrange
    const { traffic, user } = await openDeepLink(signedIn);

    // Act
    await showRevision(user, "View current transcript", CURRENT_WORDING);

    // Assert
    expect(traffic.requests).toContain("GET /api/v1/meetings/meeting/transcript");
  });

  test("switching to the current transcript hides the original wording", async () => {
    // Arrange
    const { user } = await openDeepLink(signedIn);

    // Act
    await showRevision(user, "View current transcript", CURRENT_WORDING);

    // Assert
    expect(screen.queryByText(ORIGINAL_WORDING)).not.toBeInTheDocument();
  });

  test("switching back to the original transcript restores the revision in the URL", async () => {
    // Arrange
    const { user } = await openDeepLink(signedIn);
    await showRevision(user, "View current transcript", CURRENT_WORDING);

    // Act
    await showRevision(user, "View original transcript", ORIGINAL_WORDING);

    // Assert
    expect(window.location.search).toBe("?revision_id=original");
  });

  test("Back returns to the current transcript's URL", async () => {
    // Act
    await goBackToCurrent(signedIn);

    // Assert
    expect(currentPath()).toBe(CURRENT_LINK);
  });

  test("Back hides the original wording", async () => {
    // Act
    await goBackToCurrent(signedIn);

    // Assert
    expect(screen.queryByText(ORIGINAL_WORDING)).not.toBeInTheDocument();
  });
});

test("Home requests no workspace details", async () => {
  // Arrange
  const traffic = renderHome();

  // Act
  await screen.findByRole("button", { name: /Demo Workspace.*Owner · 1 member/ });

  // Assert
  expect(traffic.requests.filter((request) => /workspaces\/workspace$/.test(request))).toEqual([]);
});

test("a workspace list failure returns to sign-in with its message", async () => {
  // Arrange
  window.history.replaceState(null, "", "/whadio/");
  sessionStorage.clear();
  server.use(
    http.get("/api/v1/workspaces", () =>
      HttpResponse.json(errorBody("INSUFFICIENT_ROLE", "Not allowed here"), { status: 403 }),
    ),
  );

  // Act
  render(<App />);

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Not allowed here");
});

test("a deep link to a meeting outside every list opens it", async () => {
  // Act
  await openDeepLink(true);

  // Assert
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(LINKED_TITLE);
});

test("a deep link names the meeting in the breadcrumbs", async () => {
  // Act
  await openDeepLink(true);

  // Assert
  expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent(LINKED_TITLE);
});

test("a failure reason survives a trip through the list, which lacks it", async () => {
  // Arrange
  startSession(CURRENT_LINK);
  server.use(
    http.get("/api/v1/meetings/meeting", () =>
      HttpResponse.json(
        meetingRead({ processing_state: "failed", failure_reason: FAILURE_REASON }),
      ),
    ),
    http.get("/api/v1/workspaces/workspace/meetings", () =>
      HttpResponse.json(page([meetingSummary({ processing_state: "failed" })])),
    ),
  );
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText(FAILURE_REASON);

  // Act
  await user.click(screen.getByRole("button", { name: "Demo Workspace" }));
  await user.click(await screen.findByRole("button", { name: /Weekly sync/ }));

  // Assert
  expect(await screen.findByText(FAILURE_REASON)).toBeInTheDocument();
});

test("an available recording survives a trip through the list, which lacks it", async () => {
  // Arrange
  startSession(CURRENT_LINK);
  server.use(
    http.get("/api/v1/meetings/meeting", () =>
      HttpResponse.json(meetingRead({ recording_available: true })),
    ),
    http.get("/api/v1/meetings/meeting/recording", () =>
      HttpResponse.json({ url: "", expires_at: "2026-10-25T10:05:00Z" }),
    ),
    http.get("/api/v1/workspaces/workspace/meetings", () =>
      HttpResponse.json(page([meetingSummary()])),
    ),
  );
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole("button", { name: "Demo Workspace" }));
  await user.click(await screen.findByRole("button", { name: /Weekly sync/ }));

  // Act
  await user.click(await screen.findByRole("tab", { name: "Recording" }));

  // Assert
  expect(await screen.findByText("Loading recording...")).toBeInTheDocument();
});

test("a deep link to a meeting the user cannot read says why", async () => {
  // Arrange
  startSession(CURRENT_LINK);
  server.use(
    http.get("/api/v1/meetings/meeting", () =>
      HttpResponse.json(errorBody("NOT_FOUND", "Meeting not found"), { status: 404 }),
    ),
  );

  // Act
  render(<App />);

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Meeting not found");
});

describe("a meeting that finishes while it is open", () => {
  async function watchMeeting(initial: Schemas["ProcessingState"] = "processing") {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const traffic = startSession(CURRENT_LINK);
    const live = { state: initial, polls: 0 };
    server.use(
      http.get("/api/v1/meetings/meeting", () => {
        live.polls += 1;
        return HttpResponse.json(
          meetingRead({
            processing_state: live.state,
            failure_reason: live.state === "failed" ? FAILURE_REASON : null,
          }),
        );
      }),
      http.get("/api/v1/meetings/meeting/notes", () =>
        HttpResponse.json(page([noteRead({ content: GENERATED_NOTES })])),
      ),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await screen.findByText(/when processing finishes/);
    return { traffic, live, user };
  }

  async function nextPoll() {
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
  }

  const contentRequests = (traffic: ApiTraffic) =>
    traffic.requests.filter((request) => /\/(transcript|notes)/.test(request));

  test.for(IN_PROGRESS)("requests no transcript or notes while %s", async (state) => {
    // Arrange
    const { traffic } = await watchMeeting(state);

    // Act
    await nextPoll();

    // Assert
    expect(contentRequests(traffic)).toEqual([]);
  });

  test.for(IN_PROGRESS)("keeps polling while %s", async (state) => {
    // Arrange
    const { live } = await watchMeeting(state);
    const polls = live.polls;

    // Act
    await nextPoll();

    // Assert
    expect(live.polls).toBe(polls + 1);
  });

  test("shows its notes without a reload", async () => {
    // Arrange
    const { live } = await watchMeeting();

    // Act
    live.state = "processed";
    await nextPoll();

    // Assert
    expect(await screen.findByText(GENERATED_NOTES)).toBeInTheDocument();
  });

  test.for(["processed", "failed"] as const)(
    "shows its transcript without a reload once %s",
    async (state) => {
      // Arrange
      const { live, user } = await watchMeeting();
      await user.click(screen.getByRole("tab", { name: "Transcript" }));

      // Act
      live.state = state;
      await nextPoll();

      // Assert
      expect(await screen.findByText(CURRENT_WORDING)).toBeInTheDocument();
    },
  );

  test("shows its failure without a reload", async () => {
    // Arrange
    const { live } = await watchMeeting();

    // Act
    live.state = "failed";
    await nextPoll();

    // Assert
    expect(await screen.findByRole("alert")).toHaveTextContent(FAILURE_REASON);
  });

  test("a failure requests the transcript once and not the notes", async () => {
    // Arrange
    const { live, traffic } = await watchMeeting();
    live.state = "failed";
    await nextPoll();
    await screen.findByRole("alert");

    // Act
    await nextPoll();

    // Assert
    expect(contentRequests(traffic)).toEqual(["GET /api/v1/meetings/meeting/transcript"]);
  });

  test.for(["processed", "failed"] as const)("stops polling once %s", async (state) => {
    // Arrange
    const { live } = await watchMeeting();
    live.state = state;
    await nextPoll();
    const polls = live.polls;

    // Act
    await nextPoll();
    await nextPoll();

    // Assert
    expect(live.polls).toBe(polls);
  });
});

test("a session that expires while reading meetings returns to sign-in", async () => {
  // Arrange
  startSession();
  server.use(
    http.get("/api/v1/workspaces/workspace/meetings", () =>
      HttpResponse.json(errorBody("UNAUTHENTICATED", "Sign in required"), { status: 401 }),
    ),
  );

  // Act
  render(<App />);

  // Assert
  expect(await screen.findByLabelText(/^Email/)).toBeInTheDocument();
});

test("Home reads each workspace's meetings once", async () => {
  // Arrange
  const traffic = renderHome();

  // Act
  await screen.findByText(/0 meetings, 0 active/);

  // Assert
  expect(traffic.requests.filter((request) => request.includes("/meetings"))).toEqual([
    "GET /api/v1/workspaces/workspace/meetings?limit=100",
  ]);
});

test("a finished upload opens the new meeting", async () => {
  // Arrange
  startSession();
  server.use(
    http.post("/api/v1/workspaces/workspace/meetings", () =>
      HttpResponse.json(meetingRead({ id: "meeting" }), { status: 201 }),
    ),
  );
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole("button", { name: /Demo Workspace.*Owner/ }));
  await user.click(await screen.findByRole("button", { name: "Upload" }));
  const input = document.querySelector("input[type=file]");
  if (!(input instanceof HTMLInputElement)) throw new Error("The dialog has no file input.");
  await user.upload(input, new File(["RIFF"], "standup.wav", { type: "audio/wav" }));

  // Act
  await user.click(screen.getByRole("button", { name: "Queue processing" }));

  // Assert
  await waitFor(() => expect(currentPath()).toBe(CURRENT_LINK));
});
