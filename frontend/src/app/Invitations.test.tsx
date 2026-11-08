import { RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { expect, test } from "vitest";
import { workspaceQueries } from "@/features/workspaces/api/workspaces";
import type { Schemas } from "@/shared/api/types";
import { errorBody, page, workspaceSummary } from "@/shared/testing/fixtures";
import { server } from "@/shared/testing/server";
import { App } from "./App";
import { createApp } from "./create-app";
import { AppProviders } from "./providers";

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
  refusesSession?: boolean;
}

function serveInvitationApi({
  accountExists,
  signedIn = false,
  refusesSession = false,
}: InvitationApiOptions) {
  let authenticated = signedIn;
  const traffic = {
    urls: [] as string[],
    acceptBodies: [] as unknown[],
    registerBodies: [] as unknown[],
  };
  server.use(
    http.get("/api/v1/users/me", ({ request }) => {
      traffic.urls.push(request.url);
      return authenticated
        ? HttpResponse.json(USER)
        : HttpResponse.json(errorBody("UNAUTHENTICATED", "Sign in required"), { status: 401 });
    }),
    http.post("/api/v1/invitations/:invitation_id/preview", async ({ request }) => {
      traffic.urls.push(request.url);
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
      authenticated = !refusesSession;
      return HttpResponse.json({ user: USER });
    }),
    http.post("/api/v1/invitations/:invitation_id/accept", async ({ request }) => {
      traffic.urls.push(request.url);
      traffic.acceptBodies.push(await request.json());
      return authenticated
        ? HttpResponse.json(MEMBERSHIP)
        : HttpResponse.json(errorBody("UNAUTHENTICATED", "Sign in required"), { status: 401 });
    }),
    http.post("/api/v1/invitations/:invitation_id/register", async ({ request }) => {
      traffic.urls.push(request.url);
      traffic.registerBodies.push(await request.json());
      authenticated = !refusesSession;
      return HttpResponse.json({ user: USER, membership: MEMBERSHIP }, { status: 201 });
    }),
    http.get("/api/v1/workspaces", ({ request }) => {
      traffic.urls.push(request.url);
      if (refusesSession && !authenticated) {
        return HttpResponse.json(errorBody("UNAUTHENTICATED", "Sign in required"), { status: 401 });
      }
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

function openInvitation(app?: ReturnType<typeof createApp>) {
  window.history.replaceState(null, "", `/invitations/${ID}#token=${TOKEN}`);
  render(
    app ? (
      <AppProviders queryClient={app.queryClient}>
        <RouterProvider router={app.router} />
      </AppProviders>
    ) : (
      <App />
    ),
  );
  return userEvent.setup();
}

async function signInLocally(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Sign in" }));
  await user.type(await screen.findByLabelText(/^Email/), USER.email);
  await user.type(screen.getByLabelText(/^Password/), "StrongPassword1");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

async function fillRegistration(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText(/^Name/), USER.name);
  await user.type(screen.getByLabelText(/^Password/), "StrongPassword1");
  await user.click(screen.getByRole("checkbox"));
}

function acceptInvitation(user: ReturnType<typeof userEvent.setup>) {
  return screen
    .findByRole("button", { name: "Accept invitation" })
    .then((button) => user.click(button));
}

function submitRegistration(user: ReturnType<typeof userEvent.setup>) {
  return user.click(screen.getByRole("button", { name: "Create account and join" }));
}

test("acceptance after local sign-in redirects into the invited workspace", async () => {
  // Arrange
  serveInvitationApi({ accountExists: true });
  const user = openInvitation();
  await signInLocally(user);

  // Act
  await acceptInvitation(user);

  // Assert
  await waitFor(() => expect(window.location.pathname).toBe(`/workspaces/${WORKSPACE_ID}`));
});

test("acceptance clears the invitation fragment", async () => {
  // Arrange
  serveInvitationApi({ accountExists: true, signedIn: true });
  const user = openInvitation();

  // Act
  await acceptInvitation(user);

  // Assert
  await waitFor(() => expect(window.location.hash).toBe(""));
});

test("acceptance sends the token in the request body", async () => {
  // Arrange
  const traffic = serveInvitationApi({ accountExists: true, signedIn: true });
  const user = openInvitation();

  // Act
  await acceptInvitation(user);

  // Assert
  await waitFor(() => expect(traffic.acceptBodies).toEqual([{ token: TOKEN }]));
});

test("registration redirects into the invited workspace", async () => {
  // Arrange
  serveInvitationApi({ accountExists: false });
  const user = openInvitation();
  await fillRegistration(user);

  // Act
  await submitRegistration(user);

  // Assert
  await waitFor(() => expect(window.location.pathname).toBe(`/workspaces/${WORKSPACE_ID}`));
});

test("registration sends the token in the request body", async () => {
  // Arrange
  const traffic = serveInvitationApi({ accountExists: false });
  const user = openInvitation();
  await fillRegistration(user);

  // Act
  await submitRegistration(user);

  // Assert
  await waitFor(() =>
    expect(traffic.registerBodies).toEqual([
      {
        token: TOKEN,
        name: USER.name,
        password: "StrongPassword1",
        accept_terms: true,
      },
    ]),
  );
});

test.each(["acceptance", "registration"] as const)(
  "%s excludes the token from request URLs",
  async (flow) => {
    // Arrange
    const registering = flow === "registration";
    const traffic = serveInvitationApi({ accountExists: !registering, signedIn: !registering });
    const user = openInvitation();
    if (registering) await fillRegistration(user);

    // Act
    await (registering ? submitRegistration(user) : acceptInvitation(user));
    await screen.findByRole("heading", { name: "Research Team" });

    // Assert
    expect(traffic.urls.filter((url) => url.includes(TOKEN))).toEqual([]);
  },
);

test("invitation registration reports a refused session after account creation", async () => {
  // Arrange
  serveInvitationApi({ accountExists: false, refusesSession: true });
  const user = openInvitation();
  await fillRegistration(user);

  // Act
  await submitRegistration(user);

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("server did not accept the session");
});

test("invitation registration removes the previous account's private data", async () => {
  // Arrange
  serveInvitationApi({ accountExists: false, signedIn: true });
  const app = createApp();
  app.queryClient.setQueryData(["previous-private-data"], ["private meeting"]);
  const user = openInvitation(app);
  await fillRegistration(user);

  // Act
  await submitRegistration(user);
  await screen.findByRole("heading", { name: "Research Team" });

  // Assert
  expect(app.queryClient.getQueryData(["previous-private-data"])).toBeUndefined();
});

test("acceptance explains a refused cookie after in-place sign-in", async () => {
  // Arrange
  serveInvitationApi({ accountExists: true, refusesSession: true });
  const user = openInvitation();
  await signInLocally(user);

  // Act
  await acceptInvitation(user);

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("server did not accept the session");
});

test("acceptance reopens local sign-in when an existing session expires", async () => {
  // Arrange
  serveInvitationApi({ accountExists: true, signedIn: true });
  server.use(
    http.post("/api/v1/invitations/:invitation_id/accept", () =>
      HttpResponse.json(errorBody("UNAUTHENTICATED", "Expired"), { status: 401 }),
    ),
  );
  const user = openInvitation();

  // Act
  await acceptInvitation(user);
  await screen.findByLabelText(/^Email/);

  // Assert
  expect(window.location.hash).toBe(`#token=${TOKEN}`);
});

test("an expired session during account switching preserves the invitation through sign-in", async () => {
  // Arrange
  serveInvitationApi({ accountExists: true, signedIn: true });
  server.use(
    http.get("/api/v1/users/me", () => HttpResponse.json({ ...USER, email: "other@example.test" })),
    http.delete("/api/v1/sessions/current", () =>
      HttpResponse.json(errorBody("UNAUTHENTICATED", "Expired"), { status: 401 }),
    ),
  );
  const user = openInvitation();

  // Act
  await user.click(await screen.findByRole("button", { name: "Use a different account" }));
  await user.type(await screen.findByLabelText(/^Email/), USER.email);
  await user.type(screen.getByLabelText(/^Password/), "StrongPassword1");
  await user.click(screen.getByRole("button", { name: "Sign in" }));

  // Assert
  expect(await screen.findByRole("button", { name: "Accept invitation" })).toBeInTheDocument();
  expect(window.location.hash).toBe(`#token=${TOKEN}`);
});

test("a failed account check offers retry and local sign-in", async () => {
  // Arrange
  serveInvitationApi({ accountExists: true });
  server.use(
    http.get("/api/v1/users/me", () =>
      HttpResponse.json(errorBody("INTEGRATION_UNAVAILABLE", "Account check unavailable"), {
        status: 503,
      }),
    ),
  );
  window.history.replaceState(null, "", `/invitations/${ID}#token=${TOKEN}`);
  const { queryClient, router } = createApp();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  const user = userEvent.setup();
  await screen.findByRole("button", { name: "Retry account check" });

  // Act
  await user.click(screen.getByRole("button", { name: "Sign in" }));

  // Assert
  expect(await screen.findByLabelText(/^Email/)).toBeInTheDocument();
  expect(window.location.hash).toBe(`#token=${TOKEN}`);
});

test("acceptance refreshes an already cached workspace list", async () => {
  // Arrange
  serveInvitationApi({ accountExists: true, signedIn: true });
  window.history.replaceState(null, "", `/invitations/${ID}#token=${TOKEN}`);
  const { queryClient, router } = createApp();
  queryClient.setQueryData(workspaceQueries.list().queryKey, page([]));
  render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  const user = userEvent.setup();

  // Act
  await user.click(await screen.findByRole("button", { name: "Accept invitation" }));
  await waitFor(() => expect(window.location.pathname).toBe(`/workspaces/${WORKSPACE_ID}`));

  // Assert
  expect(queryClient.getQueryData(workspaceQueries.list().queryKey)).toEqual(
    page([workspaceSummary({ id: WORKSPACE_ID, name: "Research Team", my_role: "member" })]),
  );
});

test("retrying a failed account check restores acceptance without losing the token", async () => {
  // Arrange
  serveInvitationApi({ accountExists: true, signedIn: true });
  let unavailable = true;
  server.use(
    http.get("/api/v1/users/me", () =>
      unavailable
        ? HttpResponse.json(errorBody("INTEGRATION_UNAVAILABLE", "Account check unavailable"), {
            status: 503,
          })
        : HttpResponse.json(USER),
    ),
  );
  window.history.replaceState(null, "", `/invitations/${ID}#token=${TOKEN}`);
  const { queryClient, router } = createApp();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  const user = userEvent.setup();
  await screen.findByRole("button", { name: "Retry account check" });
  unavailable = false;

  // Act
  await user.click(screen.getByRole("button", { name: "Retry account check" }));

  // Assert
  expect(await screen.findByRole("button", { name: "Accept invitation" })).toBeInTheDocument();
  expect(window.location.hash).toBe(`#token=${TOKEN}`);
});
