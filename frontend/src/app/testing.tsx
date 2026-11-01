import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import { HttpResponse, type HttpResponseResolver, http, type JsonBodyType } from "msw";
import type { ReactElement } from "react";
import { vi } from "vitest";
import { page } from "@/shared/testing/fixtures";
import { server } from "@/shared/testing/server";

export const ORIGINAL_WORDING = "Original uncorrected wording";
export const CURRENT_WORDING = "Current corrected wording";
export const LINKED_TITLE = "Linked meeting outside the first page";

type ApiTraffic = { requests: string[]; signIns: unknown[] };

export function transcript(original: boolean) {
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

export function serveApi(signedIn: boolean): ApiTraffic {
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
      "/api/v1/users/me",
      member(() => ({ id: "member", email: "member@example.com", name: "Demo Member" })),
    ),
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

export async function signIn(user: UserEvent) {
  await user.type(await screen.findByLabelText(/^Email/), "member@example.com");
  await user.type(screen.getByLabelText(/^Password/), "test-password");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

export function stubViewportWidth(width: number) {
  vi.stubGlobal("matchMedia", (query: string) => {
    const min = /min-width:\s*([\d.]+)px/.exec(query)?.[1];
    const max = /max-width:\s*([\d.]+)px/.exec(query)?.[1];
    return {
      matches: (!min || width >= Number(min)) && (!max || width <= Number(max)),
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
    };
  });
}

// For components that hold links: any path matches, and only `ui` renders.
export function renderAtPath(ui: ReactElement, path = "/") {
  const rootRoute = createRootRoute();
  const anyPath = createRoute({ getParentRoute: () => rootRoute, path: "$", component: () => ui });
  const router = createRouter({
    routeTree: rootRoute.addChildren([anyPath]),
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  render(<RouterProvider router={router} />);
  return router;
}
