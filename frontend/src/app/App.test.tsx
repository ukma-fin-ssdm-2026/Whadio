import { render, screen } from "@testing-library/react";
import { type UserEvent, userEvent } from "@testing-library/user-event";
import { HttpResponse, type HttpResponseResolver, http, type JsonBodyType } from "msw";
import { describe, expect, test } from "vitest";
import { server } from "@/shared/testing/server";
import { App } from "./App";

const DEEP_LINK = "/whadio/meetings/meeting?revision_id=original";
const CURRENT_LINK = "/whadio/meetings/meeting";
const ORIGINAL_WORDING = "Original uncorrected wording";
const CURRENT_WORDING = "Current corrected wording";

type ApiTraffic = { requests: string[]; signIns: unknown[] };

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
      member(() => ({ items: [] })),
    ),
    http.get(
      "/api/v1/meetings/meeting",
      member(() => ({
        id: "meeting",
        workspace_id: "workspace",
        name: "Linked meeting outside the first page",
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
