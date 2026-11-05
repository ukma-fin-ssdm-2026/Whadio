import { RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, test } from "vitest";
import { sessionQueries } from "@/features/accounts/api/session";
import { errorBody, page } from "@/shared/testing/fixtures";
import { server } from "@/shared/testing/server";
import { App } from "./App";
import { createApp } from "./create-app";
import { AppProviders } from "./providers";

const ID = "3f6c1d2e-8a4b-4c5d-9e0f-1a2b3c4d5e6f";
const TOKEN = "synthetic-secret";
const PASSWORD = "ExamplePassword1";
const USER = {
  id: ID,
  email: "synthetic@example.com",
  name: "Example User",
  is_administrator: false,
  created_at: "2026-11-05T00:00:00Z",
};

function open(kind = "registrations", fragment = `#token=${TOKEN}`, basepath?: string) {
  window.history.replaceState(null, "", `${basepath ?? "/"}${kind}/${ID}${fragment}`);
  render(<App basepath={basepath} />);
  return userEvent.setup();
}

async function fill(
  user: ReturnType<typeof userEvent.setup>,
  registration = true,
  password = PASSWORD,
) {
  if (registration) {
    await user.type(await screen.findByLabelText(/^Name/), USER.name);
    await user.click(screen.getByRole("checkbox"));
  }
  await user.click(await screen.findByLabelText(/^New password/));
  await user.paste(password);
}

test("registration consumes a fragment token in the body and enters the signed-in app", async () => {
  // Arrange
  const requests: { url: string; body: unknown }[] = [];
  server.use(
    http.post("/api/v1/registrations/:id/complete", async ({ request }) => {
      requests.push({ url: request.url, body: await request.json() });
      return HttpResponse.json(USER, { status: 201 });
    }),
    http.get("/api/v1/workspaces", () => HttpResponse.json(page([]))),
  );
  const user = open();
  await fill(user);

  // Act
  await user.click(screen.getByRole("button", { name: "Create account" }));

  // Assert
  await screen.findByRole("heading", { name: "Workspaces" });
  expect(requests).toEqual([
    {
      url: `${window.location.origin}/api/v1/registrations/${ID}/complete`,
      body: { token: TOKEN, name: USER.name, password: PASSWORD, accept_terms: true },
    },
  ]);
  expect(window.location.hash).toBe("");
});

test("registration requires explicit Terms acceptance without submitting", async () => {
  // Arrange
  const user = open();
  await fill(user);
  await user.click(screen.getByRole("checkbox"));

  // Act
  await user.click(screen.getByRole("button", { name: "Create account" }));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Accept the Terms");
});

test("reset sends only the token and password then shows sign-in confirmation", async () => {
  // Arrange
  let body: unknown;
  server.use(
    http.post("/api/v1/password-resets/:id/complete", async ({ request }) => {
      body = await request.json();
      return new HttpResponse(null, { status: 204 });
    }),
  );
  const user = open("password-resets");
  await fill(user, false);

  // Act
  await user.click(screen.getByRole("button", { name: "Save new password" }));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Your password has been changed");
  expect(body).toEqual({ token: TOKEN, password: PASSWORD });
  expect(window.location.pathname).toBe("/sign-in");
  expect(window.location.hash).toBe("");
});

describe.each(["registrations", "password-resets"])("%s", (kind) => {
  test.each([
    `A1${"x".repeat(10)}`,
    `A1${"x".repeat(126)}`,
    `A1${"😀".repeat(10)}`,
    `А²${"x".repeat(10)}`,
  ])("accepts a boundary or Unicode password", async (password) => {
    // Arrange
    let submitted = false;
    server.use(
      http.post(`/api/v1/${kind}/:id/complete`, () => {
        submitted = true;
        return HttpResponse.json(errorBody("LINK_INVALID", "Not usable"), { status: 404 });
      }),
    );
    const user = open(kind);
    await fill(user, kind === "registrations", password);

    // Act
    await user.click(screen.getByRole("button"));
    await screen.findByRole("alert");

    // Assert
    expect(submitted).toBe(true);
  });

  test("disables submission while awaiting the server", async () => {
    // Arrange
    let release: (() => void) | undefined;
    server.use(
      http.post(`/api/v1/${kind}/:id/complete`, async () => {
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        return HttpResponse.json(errorBody("LINK_INVALID", "Not usable"), { status: 404 });
      }),
    );
    const user = open(kind);
    await fill(user, kind === "registrations");

    // Act
    await user.click(screen.getByRole("button"));

    // Assert
    expect(await screen.findByRole("button", { name: "Saving..." })).toBeDisabled();
    release?.();
    await screen.findByRole("alert");
  });

  test.each(["", "#token=", "#token=one&token=two"])(
    "refuses missing or ambiguous token %s without exposing it",
    async (fragment) => {
      // Act
      open(kind, fragment);

      // Assert
      expect(await screen.findByRole("alert")).toHaveTextContent("This link cannot be used");
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
    },
  );

  test("keeps the token out of the rendered page and outgoing links", async () => {
    // Act
    open(kind);
    await screen.findByLabelText(/^New password/);

    // Assert
    expect(document.body).not.toHaveTextContent(TOKEN);
    for (const link of screen.getAllByRole("link"))
      expect(link.getAttribute("href")).not.toContain(TOKEN);
  });

  test.each(["shortA1", "a".repeat(12), "A".repeat(12), `A1${"x".repeat(127)}`])(
    "refuses weak password %s",
    async (password) => {
      // Arrange
      const user = open(kind);
      await fill(user, kind === "registrations", password);

      // Act
      await user.click(
        screen.getByRole("button", {
          name: kind === "registrations" ? "Create account" : "Save new password",
        }),
      );

      // Assert
      await waitFor(() =>
        expect(screen.getByLabelText(/^New password/)).toHaveAttribute("aria-invalid", "true"),
      );
    },
  );

  test("shows the same dead-link message for a server refusal", async () => {
    // Arrange
    server.use(
      http.post(`/api/v1/${kind}/:id/complete`, () =>
        HttpResponse.json(errorBody("LINK_INVALID", "Not usable"), { status: 404 }),
      ),
    );
    const user = open(kind);
    await fill(user, kind === "registrations");

    // Act
    await user.click(
      screen.getByRole("button", {
        name: kind === "registrations" ? "Create account" : "Save new password",
      }),
    );

    // Assert
    expect(await screen.findByRole("alert")).toHaveTextContent("This link cannot be used");
    expect(screen.queryByLabelText(/^New password/)).not.toBeInTheDocument();
  });

  test("keeps a failed request retryable", async () => {
    // Arrange
    server.use(http.post(`/api/v1/${kind}/:id/complete`, () => HttpResponse.error()));
    const user = open(kind);
    await fill(user, kind === "registrations");

    // Act
    await user.click(
      screen.getByRole("button", {
        name: kind === "registrations" ? "Create account" : "Save new password",
      }),
    );

    // Assert
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server");
    expect(screen.getByRole("button")).toBeEnabled();
  });
});

test("the Terms link preserves a deployment base path and opens a separate tab", async () => {
  // Act
  open("registrations", `#token=${TOKEN}`, "/whadio/");

  // Assert
  const link = await screen.findByRole("link", { name: "Terms and Conditions" });
  expect(link).toHaveAttribute("href", "/whadio/terms");
  expect(link).toHaveAttribute("target", "_blank");
});

test("Terms are public and describe recording consent and sharing restrictions", async () => {
  // Act
  window.history.replaceState(null, "", "/terms");
  render(<App />);

  // Assert
  expect(await screen.findByRole("heading", { name: "Terms and Conditions" })).toBeInTheDocument();
  expect(screen.getByText(/obtain the participants’ consent/)).toBeInTheDocument();
  expect(screen.getByText(/only with people authorised/)).toBeInTheDocument();
});

test.each(["registrations", "password-resets"])(
  "%s replaces a previously cached session and private data",
  async (kind) => {
    // Arrange
    window.history.replaceState(null, "", `/${kind}/${ID}#token=${TOKEN}`);
    const { router, queryClient } = createApp();
    queryClient.setQueryData(sessionQueries.me().queryKey, () => ({
      ...USER,
      id: "previous-user",
    }));
    queryClient.setQueryData(["previous-private-data"], "private");
    server.use(
      http.post(`/api/v1/${kind}/:id/complete`, () =>
        kind === "registrations"
          ? HttpResponse.json(USER, { status: 201 })
          : new HttpResponse(null, { status: 204 }),
      ),
      http.get("/api/v1/workspaces", () => HttpResponse.json(page([]))),
    );
    render(
      <AppProviders queryClient={queryClient}>
        <RouterProvider router={router} />
      </AppProviders>,
    );
    const user = userEvent.setup();
    await fill(user, kind === "registrations");

    // Act
    await user.click(screen.getByRole("button"));
    await waitFor(() =>
      expect(window.location.pathname).toBe(kind === "registrations" ? "/" : "/sign-in"),
    );

    // Assert
    expect(queryClient.getQueryData(["previous-private-data"])).toBeUndefined();
    expect(queryClient.getQueryData(sessionQueries.me().queryKey)).toEqual(
      kind === "registrations" ? USER : null,
    );
  },
);

test("registration reports a refused session after account creation", async () => {
  // Arrange
  server.use(
    http.post("/api/v1/registrations/:id/complete", () => HttpResponse.json(USER, { status: 201 })),
    http.get("/api/v1/workspaces", () =>
      HttpResponse.json(errorBody("UNAUTHENTICATED", "Sign in required"), { status: 401 }),
    ),
  );
  const user = open();
  await fill(user);

  // Act
  await user.click(screen.getByRole("button"));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("server did not accept the session");
});

test("a server password validation error stays beside the password", async () => {
  // Arrange
  server.use(
    http.post("/api/v1/password-resets/:id/complete", () =>
      HttpResponse.json(
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "Invalid fields",
            request_id: "request",
            details: [{ field: "password", message: "Choose another password" }],
          },
        },
        { status: 422 },
      ),
    ),
  );
  const user = open("password-resets");
  await fill(user, false);

  // Act
  await user.click(screen.getByRole("button"));

  // Assert
  await waitFor(() =>
    expect(screen.getByLabelText(/^New password/)).toHaveAccessibleDescription(
      "Choose another password",
    ),
  );
});
