import { focusManager } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { type UserEvent, userEvent } from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, test, vi } from "vitest";
import { POLL_INTERVAL_MS } from "@/features/meetings/api/meetings";
import type { Schemas } from "@/shared/api/types";
import { errorBody, meetingRead, meetingSummary, noteRead, page } from "@/shared/testing/fixtures";
import { server } from "@/shared/testing/server";
import { App } from "./App";
import {
  CURRENT_WORDING,
  LINKED_TITLE,
  ORIGINAL_WORDING,
  serveApi,
  signIn,
  transcript,
} from "./testing";

const DEEP_LINK = "/meetings/meeting?revision_id=original";
const CURRENT_LINK = "/meetings/meeting";
const IN_PROGRESS = ["recording", "queued", "processing"] as const;
const BEFORE_TRANSCRIPTION = ["recording", "queued"] as const;
const FAILURE_REASON = "transcription_failed";
const FAILURE_TEXT = "This recording could not be transcribed.";
const GENERATED_NOTES = "Decisions from the weekly sync";
const STALE_MS = 30_000;
const RETRIES_MS = 4_000;
const POLL_WAIT_MS = 3_000;
const REFUSALS = [
  [404, "NOT_FOUND", "Meeting not found"],
  [403, "INSUFFICIENT_ROLE", "Access denied"],
] as const;
const SERVER_FAILURE = [500, "INTERNAL_ERROR", "Unexpected server error"] as const;

afterEach(() => {
  focusManager.setFocused(undefined);
  vi.useRealTimers();
});

async function renderSignedOut() {
  window.history.replaceState(null, "", DEEP_LINK);
  const traffic = serveApi(false);
  render(<App />);
  await screen.findByLabelText(/^Email/);
  return traffic;
}

async function openDeepLink(signedIn: boolean) {
  window.history.replaceState(null, "", DEEP_LINK);
  const traffic = serveApi(signedIn);
  const user = userEvent.setup();
  render(<App />);
  if (!signedIn) await signIn(user);
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

function startSession(path = "/") {
  window.history.replaceState(null, "", path);
  return serveApi(true);
}

function renderHome() {
  const traffic = startSession();
  render(<App />);
  return traffic;
}

type MeetingFailure = readonly [number, Parameters<typeof errorBody>[0], string];

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

  test("keeps the revision in the way back", async () => {
    // Act
    await renderSignedOut();

    // Assert
    expect(new URLSearchParams(window.location.search).get("redirect")).toBe(DEEP_LINK);
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
    expect(currentPath()).toBe(`${CURRENT_LINK}?tab=transcript`);
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
    expect(currentPath()).toBe(`${CURRENT_LINK}?tab=transcript`);
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

test("a workspace list failure says why", async () => {
  // Arrange
  startSession();
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
  await screen.findByText(FAILURE_TEXT);

  // Act
  await user.click(screen.getByRole("link", { name: "Demo Workspace" }));
  await user.click(await screen.findByRole("button", { name: /Weekly sync/ }));

  // Assert
  expect(await screen.findByText(FAILURE_TEXT)).toBeInTheDocument();
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
  await user.click(await screen.findByRole("link", { name: "Demo Workspace" }));
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

async function returnToTheWindow() {
  await act(() => vi.advanceTimersByTimeAsync(STALE_MS + 1));
  focusManager.setFocused(false);
  focusManager.setFocused(true);
  await act(() => vi.advanceTimersByTimeAsync(0));
}

describe("a meeting that finishes while it is open", () => {
  async function watchMeeting(
    initial: Schemas["ProcessingState"] = "processing",
    transcribed = false,
  ) {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    startSession(CURRENT_LINK);
    const live = {
      state: initial,
      transcribed,
      polls: 0,
      content: [] as string[],
      failure: null as MeetingFailure | null,
    };
    server.use(
      http.get("/api/v1/meetings/meeting", () => {
        live.polls += 1;
        if (live.failure) {
          const [status, code, message] = live.failure;
          return HttpResponse.json(errorBody(code, message), { status });
        }
        return HttpResponse.json(
          meetingRead({
            processing_state: live.state,
            failure_reason: live.state === "failed" ? FAILURE_REASON : null,
          }),
        );
      }),
      http.get("/api/v1/meetings/meeting/notes", () => {
        live.content.push("notes");
        return HttpResponse.json(page([noteRead({ content: GENERATED_NOTES })]));
      }),
      http.get("/api/v1/meetings/meeting/transcript", () => {
        live.content.push("transcript");
        return live.transcribed
          ? HttpResponse.json(transcript(false))
          : HttpResponse.json(errorBody("NOT_TRANSCRIBED", "Not transcribed"), { status: 409 });
      }),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await screen.findByText(/when processing finishes/);
    return { live, user };
  }

  async function watchTranscriptTab(transcribed = false) {
    const watch = await watchMeeting("processing", transcribed);
    await watch.user.click(screen.getByRole("tab", { name: "Transcript" }));
    await screen.findByText(transcribed ? CURRENT_WORDING : "Transcript is not available yet.");
    return watch;
  }

  async function nextPoll() {
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
  }

  // Each answer restarts the poll's timer, so a fixed advance can outrun a slow answer.
  async function pollUntil(condition: () => boolean) {
    await vi.waitFor(
      async () => {
        await nextPoll();
        expect(condition()).toBe(true);
      },
      { timeout: POLL_WAIT_MS },
    );
  }

  async function failPoll(failure: MeetingFailure) {
    const watch = await watchMeeting();
    watch.live.failure = failure;
    await nextPoll();
    await act(() => vi.advanceTimersByTimeAsync(RETRIES_MS));
    return watch;
  }

  test.for(BEFORE_TRANSCRIPTION)("requests no transcript or notes while %s", async (state) => {
    // Arrange
    const { live } = await watchMeeting(state);

    // Act
    await nextPoll();

    // Assert
    expect(live.content).toEqual([]);
  });

  test("keeps asking for a transcript that does not exist yet at the poll's pace", async () => {
    // Arrange
    const { live } = await watchMeeting();

    // Act
    await pollUntil(() => live.content.length >= 3);

    // Assert
    expect(live.content).toEqual(["transcript", "transcript", "transcript"]);
  });

  test("shows a transcript that arrives while processing without a reload", async () => {
    // Arrange
    const { live } = await watchTranscriptTab();

    // Act
    live.transcribed = true;
    await nextPoll();

    // Assert
    expect(await screen.findByText(CURRENT_WORDING)).toBeInTheDocument();
  });

  test("stops asking once the transcript has arrived", async () => {
    // Arrange
    const { live } = await watchTranscriptTab();
    live.transcribed = true;
    await nextPoll();
    await screen.findByText(CURRENT_WORDING);
    const requests = live.content.length;

    // Act
    await nextPoll();
    await nextPoll();

    // Assert
    expect(live.content).toHaveLength(requests);
  });

  test("does not refetch a loaded transcript on each poll", async () => {
    // Arrange
    const { live } = await watchTranscriptTab(true);

    // Act
    await nextPoll();
    await nextPoll();

    // Assert
    expect(live.content).toEqual(["transcript"]);
  });

  test("does not ask again for a loaded transcript once the meeting is processed", async () => {
    // Arrange
    const { live } = await watchTranscriptTab(true);

    // Act
    live.state = "processed";
    await nextPoll();

    // Assert
    expect(live.content.filter((request) => request === "transcript")).toHaveLength(1);
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
      const { live } = await watchTranscriptTab();

      // Act
      live.transcribed = true;
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
    expect(await screen.findByRole("alert")).toHaveTextContent(FAILURE_TEXT);
  });

  test("a failure ends the requests for the transcript and never asks for the notes", async () => {
    // Arrange
    const { live } = await watchMeeting();
    live.state = "failed";
    await nextPoll();
    await screen.findByRole("alert");
    const requests = live.content.length;

    // Act
    await nextPoll();
    await nextPoll();

    // Assert
    expect(live.content).toEqual(Array(requests).fill("transcript"));
  });

  test.for(REFUSALS)("a poll refused with %i says why", async (refusal) => {
    // Act
    await failPoll(refusal);

    // Assert
    expect(screen.getByRole("alert")).toHaveTextContent(refusal[2]);
  });

  test.for(REFUSALS)("a poll refused with %i leaves no cached page", async (refusal) => {
    // Act
    await failPoll(refusal);

    // Assert
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument();
  });

  test.for(REFUSALS)("a poll refused with %i ends the polling", async (refusal) => {
    // Arrange
    const { live } = await failPoll(refusal);
    const polls = live.polls;

    // Act
    await nextPoll();
    await nextPoll();

    // Assert
    expect(live.polls).toBe(polls);
  });

  test("a refused meeting can be left", async () => {
    // Arrange
    const { user } = await failPoll(REFUSALS[0]);
    screen.getByRole("alert");

    // Act
    await user.click(screen.getByRole("link", { name: "Home" }));

    // Assert
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  test("a failed poll keeps the page", async () => {
    // Act
    await failPoll(SERVER_FAILURE);

    // Assert
    expect(screen.getByRole("tabpanel")).toBeInTheDocument();
  });

  test("a failed poll says so above the page", async () => {
    // Act
    await failPoll(SERVER_FAILURE);

    // Assert
    expect(screen.getByRole("alert")).toHaveTextContent(SERVER_FAILURE[2]);
  });

  test("a failed poll leaves the polling on", async () => {
    // Arrange
    const { live } = await failPoll(SERVER_FAILURE);
    const polls = live.polls;

    // Act
    await nextPoll();

    // Assert
    expect(live.polls).toBeGreaterThan(polls);
  });

  test("the next good poll clears a failed poll's banner", async () => {
    // Arrange
    const { live } = await failPoll(SERVER_FAILURE);
    screen.getByRole("alert");
    live.failure = null;

    // Act
    await nextPoll();

    // Assert
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  test("a failed refetch of a finished meeting shows the banner", async () => {
    // Arrange
    const { live } = await watchMeeting();
    live.state = "processed";
    await nextPoll();
    live.failure = SERVER_FAILURE;

    // Act
    await returnToTheWindow();
    await act(() => vi.advanceTimersByTimeAsync(RETRIES_MS));

    // Assert
    expect(screen.getByRole("alert")).toHaveTextContent(SERVER_FAILURE[2]);
  });

  test("a session that ends during a poll returns to sign-in", async () => {
    // Act
    await failPoll([401, "UNAUTHENTICATED", "Sign in required"]);

    // Assert
    expect(await screen.findByLabelText(/^Email/)).toBeInTheDocument();
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

describe("a recording that retention deletes while it is open", () => {
  async function watchRecording() {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    startSession(CURRENT_LINK);
    const live = { available: true };
    server.use(
      http.get("/api/v1/meetings/meeting", () =>
        HttpResponse.json(meetingRead({ recording_available: live.available })),
      ),
      http.get("/api/v1/meetings/meeting/recording", () =>
        HttpResponse.json({
          url: "https://storage.example/link",
          expires_at: "2026-10-25T10:05:00Z",
        }),
      ),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await user.click(await screen.findByRole("tab", { name: "Recording" }));
    await screen.findByLabelText("Weekly sync recording");
    return live;
  }

  test("coming back to the window takes the player away", async () => {
    // Arrange
    const live = await watchRecording();

    // Act
    live.available = false;
    await returnToTheWindow();

    // Assert
    expect(await screen.findByText("Recording is not available")).toBeInTheDocument();
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
