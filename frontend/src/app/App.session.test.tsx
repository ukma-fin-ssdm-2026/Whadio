import { act, render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, expect, test, vi } from "vitest";
import { errorBody, page, workspaceSummary } from "@/shared/testing/fixtures";
import { server } from "@/shared/testing/server";
import { App } from "./App";

const POLL_INTERVAL_MS = 10_000;

const meetingInProgress = {
  id: "meeting",
  workspace_id: "workspace",
  name: "Weekly sync",
  recorded_at: "2026-10-25T10:00:00Z",
  processing_state: "processing",
  duration_seconds: 5,
  source_type: "upload",
};

function serveSession(meetings: () => Response) {
  const workspaceReads: string[] = [];
  window.history.replaceState(null, "", "/");
  server.use(
    http.get("/api/v1/users/me", () =>
      HttpResponse.json({ id: "member", email: "member@example.com", name: "Member" }),
    ),
    http.get("/api/v1/workspaces", ({ request }) => {
      workspaceReads.push(request.url);
      return HttpResponse.json(page([workspaceSummary()]));
    }),
    http.get("/api/v1/workspaces/workspace/meetings", meetings),
    http.post("/api/v1/sessions", () =>
      HttpResponse.json({ user: { id: "member", email: "member@example.com", name: "Member" } }),
    ),
  );
  return workspaceReads;
}

const sessionExpired = () =>
  HttpResponse.json(errorBody("UNAUTHENTICATED", "Sign in required"), { status: 401 });

afterEach(() => {
  vi.useRealTimers();
});

test("a 401 from the first meeting list returns to sign-in", async () => {
  // Arrange
  serveSession(sessionExpired);

  // Act
  render(<App />);

  // Assert
  expect(await screen.findByLabelText(/^Email/)).toBeInTheDocument();
});

test("a 401 while polling meetings returns to sign-in", async () => {
  // Arrange
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let expired = false;
  serveSession(() => (expired ? sessionExpired() : HttpResponse.json(page([meetingInProgress]))));
  render(<App />);
  await screen.findByText(/1 meeting, 1 active/);

  // Act
  expired = true;
  await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));

  // Assert
  expect(await screen.findByLabelText(/^Email/)).toBeInTheDocument();
});

test("signing back in after a 401 reads the workspaces again", async () => {
  // Arrange
  let expired = true;
  const workspaceReads = serveSession(() =>
    expired ? sessionExpired() : HttpResponse.json(page([])),
  );
  const user = userEvent.setup();
  render(<App />);
  await user.type(await screen.findByLabelText(/^Email/), "member@example.com");
  await user.type(screen.getByLabelText(/^Password/), "test-password");
  expired = false;

  // Act
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  await screen.findByText(/0 meetings, 0 active/);

  // Assert
  expect(workspaceReads).toHaveLength(2);
});
