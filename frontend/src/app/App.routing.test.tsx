import { act, render, screen, waitFor, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, test, vi } from "vitest";
import { POLL_INTERVAL_MS } from "@/features/meetings/api/meetings";
import { errorBody, meetingRead, meetingSummary, page } from "@/shared/testing/fixtures";
import { server } from "@/shared/testing/server";
import { App } from "./App";
import {
  CURRENT_WORDING,
  LINKED_TITLE,
  ORIGINAL_WORDING,
  serveApi,
  signIn,
  stubViewportWidth,
} from "./testing";

const SIGN_IN_FORM = /^Email/;
const MEETING_LINK = "/meetings/meeting";
const REVISION_LINK = `${MEETING_LINK}?revision_id=original`;
const RETRIES_MS = 4_000;
const SESSION_REFUSED = /did not accept the session/;
const SIGN_IN_REQUIRED = errorBody("UNAUTHENTICATED", "Sign in required");
const LIST_ROW = /Weekly sync/;

const expired = () => HttpResponse.json(SIGN_IN_REQUIRED, { status: 401 });

const currentPath = () => window.location.pathname + window.location.search;
const returnTarget = () => new URLSearchParams(window.location.search).get("redirect");

function open(path: string, signedIn = true, basepath?: string) {
  window.history.replaceState(null, "", path);
  const traffic = serveApi(signedIn);
  render(<App basepath={basepath} />);
  return { traffic, user: userEvent.setup() };
}

function serveWorkspaceMeetings() {
  server.use(
    http.get("/api/v1/workspaces/workspace/meetings", () =>
      HttpResponse.json(page([meetingSummary()])),
    ),
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("a signed-out visit", () => {
  test("asks who is signed in only once", async () => {
    // Act
    const { traffic } = open(MEETING_LINK, false);
    await screen.findByLabelText(SIGN_IN_FORM);

    // Assert
    expect(traffic.requests.filter((request) => request.includes("/users/me"))).toHaveLength(1);
  });

  test("leaves no entry for Back to bounce on", async () => {
    // Arrange
    const entries = window.history.length;

    // Act
    open(MEETING_LINK, false);
    await screen.findByLabelText(SIGN_IN_FORM);

    // Assert
    expect(window.history.length).toBe(entries);
  });

  test("shows no error on the form", async () => {
    // Act
    open(MEETING_LINK, false);
    await screen.findByLabelText(SIGN_IN_FORM);

    // Assert
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  test("to Home needs no way back", async () => {
    // Act
    open("/", false);
    await screen.findByLabelText(SIGN_IN_FORM);

    // Assert
    expect(currentPath()).toBe("/sign-in");
  });
});

describe("the sign-in page", () => {
  test("sends a signed-in visitor to the target", async () => {
    // Act
    open(`/sign-in?redirect=${encodeURIComponent(MEETING_LINK)}`);

    // Assert
    await waitFor(() => expect(currentPath()).toBe(MEETING_LINK));
  });

  test("sends a signed-in visitor without a target Home", async () => {
    // Act
    open("/sign-in");

    // Assert
    await waitFor(() => expect(currentPath()).toBe("/"));
  });

  test.for([
    ["an absolute URL", "https://evil.example/"],
    ["a protocol-relative URL", "//evil.example/"],
    ["a backslash trick", "/\\evil.example"],
    ["a script URL", "javascript:alert(1)"],
  ])("sends a signed-in visitor Home instead of to %s", async ([, target]) => {
    // Act
    open(`/sign-in?redirect=${encodeURIComponent(target ?? "")}`);

    // Assert
    await waitFor(() => expect(currentPath()).toBe("/"));
  });

  test.for([
    ["an absolute URL", "https://evil.example/"],
    ["a protocol-relative URL", "//evil.example/"],
    ["a backslash trick", "/\\evil.example"],
    ["a script URL", "javascript:alert(1)"],
  ])("goes Home after signing in instead of to %s", async ([, target]) => {
    // Arrange
    const { user } = open(`/sign-in?redirect=${encodeURIComponent(target ?? "")}`, false);

    // Act
    await signIn(user);

    // Assert
    await waitFor(() => expect(currentPath()).toBe("/"));
  });

  test("shows a spinner while the session is being checked", async () => {
    // Arrange
    window.history.replaceState(null, "", "/");
    serveApi(true);
    server.use(http.get("/api/v1/users/me", () => new Promise<Response>(() => {})));

    // Act
    render(<App />);

    // Assert
    expect(await screen.findByRole("progressbar", { name: "Loading" })).toBeInTheDocument();
  });

  test("still opens when the check of the session fails", async () => {
    // Arrange
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.history.replaceState(null, "", "/sign-in");
    serveApi(false);
    server.use(
      http.get("/api/v1/users/me", () =>
        HttpResponse.json(errorBody("INTERNAL_ERROR", "Unexpected"), { status: 500 }),
      ),
    );

    // Act
    render(<App />);
    await act(() => vi.advanceTimersByTimeAsync(RETRIES_MS));

    // Assert
    expect(await screen.findByLabelText(SIGN_IN_FORM)).toBeInTheDocument();
  });
});

describe("a session that ends", () => {
  async function expireWhilePolling() {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.history.replaceState(null, "", REVISION_LINK);
    serveApi(true);
    const live = { ended: false, reads: 0 };
    server.use(
      http.get("/api/v1/meetings/meeting", () => {
        live.reads += 1;
        return live.ended
          ? expired()
          : HttpResponse.json(meetingRead({ processing_state: "processing" }));
      }),
    );
    render(<App />);
    await screen.findByRole("tab", { selected: true });
    live.ended = true;
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
    await screen.findByLabelText(SIGN_IN_FORM);
    return live;
  }

  test("returns to sign-in carrying the page", async () => {
    // Act
    await expireWhilePolling();

    // Assert
    expect(returnTarget()).toBe(REVISION_LINK);
  });

  test("shows no error on the form", async () => {
    // Act
    await expireWhilePolling();

    // Assert
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  test("reads the page no more after the refused poll", async () => {
    // Act
    const { reads } = await expireWhilePolling();

    // Assert
    expect(reads).toBe(2);
  });

  test("keeps no way back to the page in the history", async () => {
    // Arrange
    const entries = window.history.length;

    // Act
    await expireWhilePolling();

    // Assert
    expect(window.history.length).toBe(entries);
  });
});

describe("a 401 straight after signing in", () => {
  async function signInToRefusedSession() {
    const { user } = open("/", false);
    server.use(http.get("/api/v1/workspaces", expired));
    await signIn(user);
  }

  test("says so on the form", async () => {
    // Act
    await signInToRefusedSession();

    // Assert
    expect(await screen.findByRole("alert")).toHaveTextContent(SESSION_REFUSED);
  });

  test("does not outlive the next good sign-in", async () => {
    // Arrange
    await signInToRefusedSession();
    await screen.findByRole("alert");
    const user = userEvent.setup();
    server.resetHandlers();
    serveApi(true);

    // Act
    await signIn(user);

    // Assert
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });
});

test("a 401 after the first data loaded says nothing on the form", async () => {
  // Arrange
  const { user } = open("/", false);
  server.use(http.get("/api/v1/workspaces/workspace/meetings", expired));

  // Act
  await signIn(user);
  await screen.findByLabelText(SIGN_IN_FORM);

  // Assert
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

describe("signing out", () => {
  async function signOut(status: number) {
    stubViewportWidth(1440);
    const { traffic, user } = open(MEETING_LINK);
    server.use(http.delete("/api/v1/sessions/current", () => new HttpResponse(null, { status })));
    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    await screen.findByLabelText(SIGN_IN_FORM);
    return traffic;
  }

  test("carries no way back", async () => {
    // Act
    await signOut(204);

    // Assert
    expect(currentPath()).toBe("/sign-in");
  });

  test("reaches the form even when the server refuses", async () => {
    // Act
    await signOut(503);

    // Assert
    expect(currentPath()).toBe("/sign-in");
  });

  test("shows no error on the form", async () => {
    // Act
    await signOut(204);

    // Assert
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("a first load that fails without a 401", () => {
  function failSession() {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.history.replaceState(null, "", REVISION_LINK);
    serveApi(true);
    server.use(
      http.get("/api/v1/users/me", () =>
        HttpResponse.json(errorBody("INTERNAL_ERROR", "Unexpected server error"), {
          status: 500,
        }),
      ),
    );
    render(<App />);
  }

  test("says why", async () => {
    // Act
    failSession();
    await act(() => vi.advanceTimersByTimeAsync(RETRIES_MS));

    // Assert
    expect(await screen.findByRole("alert")).toHaveTextContent("Unexpected server error");
  });

  test("keeps the address", async () => {
    // Act
    failSession();
    await act(() => vi.advanceTimersByTimeAsync(RETRIES_MS));
    await screen.findByRole("alert");

    // Assert
    expect(currentPath()).toBe(REVISION_LINK);
  });

  test("does not read as signed out", async () => {
    // Act
    failSession();
    await act(() => vi.advanceTimersByTimeAsync(RETRIES_MS));
    await screen.findByRole("alert");

    // Assert
    expect(screen.queryByLabelText(SIGN_IN_FORM)).not.toBeInTheDocument();
  });
});

test("a failed workspace list keeps the address", async () => {
  // Arrange
  window.history.replaceState(null, "", MEETING_LINK);
  serveApi(true);
  server.use(
    http.get("/api/v1/workspaces", () =>
      HttpResponse.json(errorBody("INSUFFICIENT_ROLE", "Not allowed here"), { status: 403 }),
    ),
  );

  // Act
  render(<App />);
  await screen.findByRole("alert");

  // Assert
  expect(currentPath()).toBe(MEETING_LINK);
});

describe("the not-found page", () => {
  const EMAILED_LINKS = [
    "/shares/share/access-requests",
    "/invitations/invitation",
    "/registrations/registration#token=emailed-secret",
    "/password-resets/reset#token=emailed-secret",
  ];

  test.for(EMAILED_LINKS)("answers %s when signed out", async (path) => {
    // Act
    open(path, false);

    // Assert
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
  });

  test.for(EMAILED_LINKS)("answers %s when signed in", async (path) => {
    // Act
    open(path);

    // Assert
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
  });

  test("shows no token from the link", async () => {
    // Act
    open("/registrations/registration#token=emailed-secret", false);
    await screen.findByRole("heading", { name: "Page not found" });

    // Assert
    expect(document.body).not.toHaveTextContent("emailed-secret");
  });

  test("offers a way Home", async () => {
    // Act
    open("/nowhere");

    // Assert
    expect(await screen.findByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
  });

  test.for(["/workspaces/not-mine", "/workspaces/not-mine/settings"])(
    "answers %s, a workspace the user is not in",
    async (path) => {
      // Act
      open(path);

      // Assert
      expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    },
  );
});

test("the library has its own address", async () => {
  // Act
  open("/meetings");

  // Assert
  expect(await screen.findByRole("heading", { name: "Meetings" })).toBeInTheDocument();
});

test("Home with no workspaces opens", async () => {
  // Arrange
  window.history.replaceState(null, "", "/");
  serveApi(true);
  server.use(http.get("/api/v1/workspaces", () => HttpResponse.json(page([]))));

  // Act
  render(<App />);

  // Assert
  expect(await screen.findByRole("heading", { name: "Workspaces" })).toBeInTheDocument();
});

describe("a workspace page", () => {
  test("names the role above the title", async () => {
    // Act
    open("/workspaces/workspace");

    // Assert
    expect(await screen.findByText("Owner workspace")).toBeInTheDocument();
  });

  test.for([
    ["/workspaces/workspace", "false"],
    ["/workspaces/workspace/settings", "true"],
  ])("at %s has the settings button pressed: %s", async ([path, pressed]) => {
    // Act
    open(path ?? "");

    // Assert
    expect(await screen.findByRole("button", { name: "Workspace settings" })).toHaveAttribute(
      "aria-pressed",
      pressed,
    );
  });

  test("the settings button opens the settings", async () => {
    // Arrange
    const { user } = open("/workspaces/workspace");

    // Act
    await user.click(await screen.findByRole("button", { name: "Workspace settings" }));

    // Assert
    await waitFor(() => expect(currentPath()).toBe("/workspaces/workspace/settings"));
  });

  test("the settings button closes the settings", async () => {
    // Arrange
    const { user } = open("/workspaces/workspace/settings");

    // Act
    await user.click(await screen.findByRole("button", { name: "Workspace settings" }));

    // Assert
    await waitFor(() => expect(currentPath()).toBe("/workspaces/workspace"));
  });
});

describe("a meeting left with Back", () => {
  async function leaveMeeting(path: string) {
    const { user } = open(path);
    serveWorkspaceMeetings();
    await user.click(await screen.findByRole("button", { name: LIST_ROW }));
    await screen.findByRole("tab", { selected: true });
    window.history.back();
    return screen.findByRole("button", { name: LIST_ROW });
  }

  test.for(["/meetings", "/workspaces/workspace"])(
    "stays marked in the list at %s",
    async (path) => {
      // Act
      const row = await leaveMeeting(path);

      // Assert
      expect(row).toHaveClass("Mui-selected");
    },
  );

  test("returns to the page it was opened from", async () => {
    // Act
    await leaveMeeting("/workspaces/workspace");

    // Assert
    expect(currentPath()).toBe("/workspaces/workspace");
  });

  test("is not marked after arriving at the list by a link", async () => {
    // Arrange
    const row = await leaveMeeting("/workspaces/workspace");
    await waitFor(() => expect(row).toHaveClass("Mui-selected"));
    const user = userEvent.setup();

    // Act
    await user.click(row);
    await screen.findByRole("tab", { selected: true });
    await user.click(await screen.findByRole("link", { name: "Demo Workspace" }));

    // Assert
    expect(await screen.findByRole("button", { name: LIST_ROW })).not.toHaveClass("Mui-selected");
  });
});

describe("a meeting's link", () => {
  test("opens the notes by default", async () => {
    // Act
    open(MEETING_LINK);

    // Assert
    expect(await screen.findByRole("tab", { selected: true })).toHaveTextContent(/^Notes$/);
  });

  test("with an empty revision opens the notes", async () => {
    // Act
    open(`${MEETING_LINK}?revision_id=`);

    // Assert
    expect(await screen.findByRole("tab", { selected: true })).toHaveTextContent(/^Notes$/);
  });

  test("keeps a revision with reserved characters intact", async () => {
    // Arrange
    const encoded = encodeURIComponent("bad&other=value");

    // Act
    const { traffic } = open(`${MEETING_LINK}?revision_id=${encoded}`);
    await screen.findByRole("tab", { selected: true });

    // Assert
    await waitFor(() =>
      expect(traffic.requests).toContain(
        `GET /api/v1/meetings/meeting/transcript?revision_id=${encoded}`,
      ),
    );
  });
});

describe("a meeting's tab in the URL", () => {
  const selectedTab = () => screen.findByRole("tab", { selected: true });

  async function clickThroughTabs() {
    const { user } = open(MEETING_LINK);
    await user.click(await screen.findByRole("tab", { name: "Transcript" }));
    await user.click(screen.getByRole("tab", { name: "Recording" }));
    await waitFor(() => expect(window.location.search).toBe("?tab=recording"));
  }

  test("a deep link opens that tab", async () => {
    // Act
    open(`${MEETING_LINK}?tab=recording`);

    // Assert
    expect(await selectedTab()).toHaveTextContent(/^Recording$/);
  });

  test("a bad value falls back to the notes", async () => {
    // Act
    open(`${MEETING_LINK}?tab=settings`);

    // Assert
    expect(await selectedTab()).toHaveTextContent(/^Notes$/);
  });

  test("a bad value falls back to the transcript for a revision", async () => {
    // Act
    open(`${REVISION_LINK}&tab=settings`);

    // Assert
    expect(await selectedTab()).toHaveTextContent(/^Transcript$/);
  });

  test("opening a meeting adds no entry for the default tab", async () => {
    // Arrange
    const entries = window.history.length;

    // Act
    open(MEETING_LINK);
    await selectedTab();

    // Assert
    expect(window.history.length).toBe(entries);
  });

  test("the default tab stays out of the URL", async () => {
    // Arrange
    const { user } = open(`${MEETING_LINK}?tab=transcript`);

    // Act
    await user.click(await screen.findByRole("tab", { name: "Notes" }));

    // Assert
    await waitFor(() => expect(currentPath()).toBe(MEETING_LINK));
  });

  test("choosing a tab keeps the scroll position", async () => {
    // Arrange
    const { user } = open(MEETING_LINK);
    const tab = await screen.findByRole("tab", { name: "Transcript" });
    vi.mocked(window.scrollTo).mockClear();

    // Act
    await user.click(tab);
    await waitFor(() => expect(window.location.search).toBe("?tab=transcript"));
    await screen.findByPlaceholderText("Search transcript");

    // Assert
    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  test("Back restores the previous tab", async () => {
    // Arrange
    await clickThroughTabs();

    // Act
    window.history.back();

    // Assert
    await waitFor(() =>
      expect(screen.getByRole("tab", { selected: true })).toHaveTextContent(/^Transcript$/),
    );
  });

  test("a chosen revision keeps its place in the URL beside the tab", async () => {
    // Arrange
    const { user } = open(REVISION_LINK);

    // Act
    await user.click(await screen.findByRole("tab", { name: "Notes" }));

    // Assert
    await waitFor(() =>
      expect(currentPath()).toBe(`${MEETING_LINK}?tab=notes&revision_id=original`),
    );
  });
});

describe.for(["/meetings", "/workspaces/workspace"])("the filters of %s", (path) => {
  const FILTER = "Filter by name";

  function serveFailedMeeting() {
    const names: (string | null)[] = [];
    server.use(
      http.get("/api/v1/workspaces/workspace/meetings", ({ request }) => {
        names.push(new URL(request.url).searchParams.get("name"));
        return HttpResponse.json(
          page([
            meetingSummary({ id: "lost", name: "Lost call", processing_state: "failed" }),
            meetingSummary({ id: "done", name: "Finished call" }),
          ]),
        );
      }),
    );
    return names;
  }

  test("a deep link fills in the name", async () => {
    // Act
    open(`${path}?q=retro`);

    // Assert
    expect(await screen.findByPlaceholderText(FILTER)).toHaveValue("retro");
  });

  test("a deep link asks the server for the name", async () => {
    // Arrange
    window.history.replaceState(null, "", `${path}?q=retro`);
    serveApi(true);
    const names = serveFailedMeeting();

    // Act
    render(<App />);
    await screen.findByText("Lost call");

    // Assert
    expect(names).toEqual(["retro"]);
  });

  test("a numeric name survives the URL", async () => {
    // Act
    open(`${path}?q=2026`);

    // Assert
    expect(await screen.findByPlaceholderText(FILTER)).toHaveValue("2026");
  });

  test("a deep link applies the state", async () => {
    // Arrange
    window.history.replaceState(null, "", `${path}?state=failed`);
    serveApi(true);
    serveFailedMeeting();

    // Act
    render(<App />);
    await screen.findByText("Lost call");

    // Assert
    expect(screen.queryByText("Finished call")).not.toBeInTheDocument();
  });

  test("a bad state shows everything", async () => {
    // Act
    open(`${path}?state=lost`);

    // Assert
    expect(await screen.findByRole("combobox")).toHaveTextContent("All states");
  });

  test("typing reaches the URL once it settles", async () => {
    // Arrange
    const { user } = open(path);

    // Act
    await user.type(await screen.findByPlaceholderText(FILTER), " retro ");

    // Assert
    await waitFor(() => expect(currentPath()).toBe(`${path}?q=retro`));
  });

  test("typing adds no history entry", async () => {
    // Arrange
    const entries = window.history.length;
    const { user } = open(path);

    // Act
    await user.type(await screen.findByPlaceholderText(FILTER), "retro");
    await waitFor(() => expect(window.location.search).toBe("?q=retro"));

    // Assert
    expect(window.history.length).toBe(entries);
  });

  test("filtering keeps the scroll position", async () => {
    // Arrange
    const { user } = open(path);
    const search = await screen.findByPlaceholderText(FILTER);
    vi.mocked(window.scrollTo).mockClear();

    // Act
    await user.type(search, "retro");
    await waitFor(() => expect(window.location.search).toBe("?q=retro"));

    // Assert
    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  test("choosing a state reaches the URL", async () => {
    // Arrange
    const { user } = open(path);

    // Act
    await user.click(await screen.findByRole("combobox"));
    await user.click(screen.getByRole("option", { name: "Failed" }));

    // Assert
    await waitFor(() => expect(currentPath()).toBe(`${path}?state=failed`));
  });

  test("choosing all states clears the URL", async () => {
    // Arrange
    const { user } = open(`${path}?state=failed`);

    // Act
    await user.click(await screen.findByRole("combobox"));
    await user.click(screen.getByRole("option", { name: "All states" }));

    // Assert
    await waitFor(() => expect(currentPath()).toBe(path));
  });
});

test("the assistant settings have their own address", async () => {
  // Act
  open("/settings/assistant");

  // Assert
  expect(await screen.findByRole("heading", { name: "AI assistant access" })).toBeInTheDocument();
});

describe("transcript search", () => {
  async function searchThenSwitchRevision() {
    const { user } = open(REVISION_LINK);
    await screen.findByText(ORIGINAL_WORDING);
    const search = screen.getByPlaceholderText("Search transcript");
    await user.type(search, "Original");
    await user.click(screen.getByRole("button", { name: "View current transcript" }));
    await screen.findByText(CURRENT_WORDING);
    return screen.getByPlaceholderText("Search transcript");
  }

  test("starts empty for another revision", async () => {
    // Act
    const search = await searchThenSwitchRevision();

    // Assert
    expect(search).toHaveValue("");
  });

  test("Forward returns to the tab the revision was chosen on", async () => {
    // Arrange
    await searchThenSwitchRevision();
    window.history.back();
    await screen.findByText(ORIGINAL_WORDING);

    // Act
    window.history.forward();

    // Assert
    expect(await screen.findByText(CURRENT_WORDING)).toBeInTheDocument();
  });
});

describe("under a deployment prefix", () => {
  test("a deep link opens the page", async () => {
    // Act
    open(`/whadio${REVISION_LINK}`, true, "/whadio/");

    // Assert
    expect(await screen.findByText(ORIGINAL_WORDING)).toBeInTheDocument();
  });

  test("signing in returns to the page under the prefix", async () => {
    // Arrange
    const { user } = open(`/whadio${REVISION_LINK}`, false, "/whadio/");

    // Act
    await signIn(user);
    await screen.findByText(ORIGINAL_WORDING);

    // Assert
    expect(currentPath()).toBe(`/whadio${REVISION_LINK}`);
  });

  test("switching revision keeps the prefix", async () => {
    // Arrange
    const { user } = open(`/whadio${REVISION_LINK}`, true, "/whadio/");
    await screen.findByText(ORIGINAL_WORDING);

    // Act
    await user.click(screen.getByRole("button", { name: "View current transcript" }));
    await screen.findByText(CURRENT_WORDING);

    // Assert
    expect(currentPath()).toBe(`/whadio${MEETING_LINK}?tab=transcript`);
  });

  test("links carry the prefix", async () => {
    // Act
    open(`/whadio${MEETING_LINK}`, true, "/whadio/");
    const breadcrumb = await screen.findByRole("navigation", { name: "Breadcrumb" });

    // Assert
    expect(within(breadcrumb).getByRole("link", { name: "Home" })).toHaveAttribute(
      "href",
      "/whadio/",
    );
  });

  test("a deep link to a meeting shows its title", async () => {
    // Act
    open(`/whadio${MEETING_LINK}`, true, "/whadio/");

    // Assert
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(LINKED_TITLE);
  });
});
