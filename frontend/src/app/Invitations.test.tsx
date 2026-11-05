import { render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { errorBody, page, workspaceSummary } from "@/shared/testing/fixtures";
import { server } from "@/shared/testing/server";
import { App } from "./App";

const ID = "11111111-1111-4111-8111-111111111111";
const WORKSPACE_ID = "22222222-2222-4222-8222-222222222222";
const USER_ID = "33333333-3333-4333-8333-333333333333";
const TOKEN = "fragment-secret";
const USER: Schemas["UserRead"] = {
  id: USER_ID,
  email: "invited@example.test",
  name: "Invited Person",
  is_administrator: false,
  created_at: "2026-11-05T10:00:00Z",
};
const MEMBERSHIP: Schemas["MembershipRead"] = {
  user_id: USER_ID,
  workspace_id: WORKSPACE_ID,
  role: "member",
  joined_at: "2026-11-05T10:00:00Z",
};

interface InvitationApiOptions {
  accountExists: boolean;
  signedIn?: boolean;
}

function serveInvitationApi({ accountExists, signedIn = false }: InvitationApiOptions) {
  let authenticated = signedIn;
  const traffic = { urls: [] as string[], bodies: [] as unknown[], currentUserReads: 0 };
  server.use(
    http.get("/api/v1/users/me", ({ request }) => {
      traffic.urls.push(request.url);
      traffic.currentUserReads += 1;
      return authenticated
        ? HttpResponse.json(USER)
        : HttpResponse.json(errorBody("UNAUTHENTICATED", "Sign in required"), { status: 401 });
    }),
    http.post("/api/v1/invitations/:invitation_id/preview", async ({ request }) => {
      traffic.urls.push(request.url);
      traffic.bodies.push(await request.json());
      return HttpResponse.json({
        workspace_id: WORKSPACE_ID,
        workspace_name: "Research Team",
        email: USER.email,
        role: "member",
        account_exists: accountExists,
      });
    }),
    http.post("/api/v1/sessions", async ({ request }) => {
      traffic.urls.push(request.url);
      traffic.bodies.push(await request.json());
      authenticated = true;
      return HttpResponse.json({ user: USER });
    }),
    http.post("/api/v1/invitations/:invitation_id/accept", async ({ request }) => {
      traffic.urls.push(request.url);
      traffic.bodies.push(await request.json());
      return HttpResponse.json(MEMBERSHIP);
    }),
    http.post("/api/v1/invitations/:invitation_id/register", async ({ request }) => {
      traffic.urls.push(request.url);
      traffic.bodies.push(await request.json());
      authenticated = true;
      return HttpResponse.json({ user: USER, membership: MEMBERSHIP }, { status: 201 });
    }),
    http.get("/api/v1/workspaces", ({ request }) => {
      traffic.urls.push(request.url);
      return HttpResponse.json(
        page([workspaceSummary({ id: WORKSPACE_ID, name: "Research Team", my_role: "member" })]),
      );
    }),
    http.get("/api/v1/workspaces/:workspace_id/meetings", ({ request }) => {
      traffic.urls.push(request.url);
      return HttpResponse.json(page([]));
    }),
    http.get("/api/v1/workspaces/:workspace_id/folders", ({ request }) => {
      traffic.urls.push(request.url);
      return HttpResponse.json(page([]));
    }),
  );
  return traffic;
}

function openInvitation() {
  window.history.replaceState(null, "", `/invitations/${ID}#token=${TOKEN}`);
  render(<App />);
  return userEvent.setup();
}

test("sign-in returns locally to the fragment and acceptance refreshes caches before redirect", async () => {
  // Arrange
  const traffic = serveInvitationApi({ accountExists: true });
  const user = openInvitation();
  await user.click(await screen.findByRole("button", { name: "Sign in" }));
  expect(window.location.hash).toBe(`#token=${TOKEN}`);
  await user.type(await screen.findByLabelText(/^Email/), USER.email);
  await user.type(screen.getByLabelText(/^Password/), "StrongPassword1");
  await user.click(screen.getByRole("button", { name: "Sign in" }));

  // Act
  await user.click(await screen.findByRole("button", { name: "Accept invitation" }));

  // Assert
  await waitFor(() => expect(window.location.pathname).toBe(`/workspaces/${WORKSPACE_ID}`));
  expect(window.location.hash).toBe("");
  expect(traffic.currentUserReads).toBeGreaterThan(1);
  expect(traffic.bodies).toContainEqual({ token: TOKEN });
  expect(traffic.urls.every((url) => !url.includes(TOKEN))).toBe(true);
});

test("registration refreshes the new session and redirects into the invited workspace", async () => {
  // Arrange
  const traffic = serveInvitationApi({ accountExists: false });
  const user = openInvitation();
  await user.type(await screen.findByLabelText(/^Name/), USER.name);
  await user.type(screen.getByLabelText(/^Password/), "StrongPassword1");
  await user.click(screen.getByRole("checkbox"));

  // Act
  await user.click(screen.getByRole("button", { name: "Create account and join" }));

  // Assert
  await waitFor(() => expect(window.location.pathname).toBe(`/workspaces/${WORKSPACE_ID}`));
  expect(traffic.currentUserReads).toBeGreaterThan(1);
  expect(traffic.bodies).toContainEqual({
    token: TOKEN,
    name: USER.name,
    password: "StrongPassword1",
    accept_terms: true,
  });
  expect(traffic.urls.every((url) => !url.includes(TOKEN))).toBe(true);
});
