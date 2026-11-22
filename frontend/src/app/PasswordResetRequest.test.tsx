import { notifyManager, type QueryClient } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { HttpResponse, http as rawHttp } from "msw";
import { expect, test } from "vitest";
import { instanceQuery } from "@/features/accounts/api/instance";
import type { Schemas } from "@/shared/api/types";
import { deferred } from "@/shared/testing/deferred";
import { errorBody } from "@/shared/testing/fixtures";
import { http, server } from "@/shared/testing/server";
import { createApp } from "./create-app";
import { AppProviders } from "./providers";

const EMAIL = "member@example.com";
const CONFIRMATION = "If an account exists for that email, we'll send a reset link.";

function reportMode(mode: Schemas["InstanceRead"]["registration_mode"]) {
  server.use(
    http.get("/api/v1/instance", ({ response }) =>
      response(200).json({ registration_mode: mode, api_version: "1" }),
    ),
  );
}

function failModeLookup() {
  server.use(rawHttp.get("/api/v1/instance", () => HttpResponse.error()));
}

function holdModeLookup() {
  const started = deferred();
  const pending = deferred();
  server.use(
    http.get("/api/v1/instance", async ({ response }) => {
      started.resolve();
      await pending.promise;
      return response(200).json({ registration_mode: "verified", api_version: "1" });
    }),
  );
  return { started: started.promise, release: pending.resolve };
}

function open(path: string) {
  server.use(
    http.get("/api/v1/users/me", ({ response }) =>
      response(401).json(errorBody("UNAUTHENTICATED", "Sign in required")),
    ),
  );
  window.history.replaceState(null, "", path);
  const { router, queryClient } = createApp();
  render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return { user: userEvent.setup(), queryClient };
}

async function submitEmail(user: ReturnType<typeof userEvent.setup>, email = EMAIL) {
  await user.type(await screen.findByRole("textbox", { name: "Email" }), email);
  await user.click(screen.getByRole("button", { name: "Send reset link" }));
}

async function refreshMode(queryClient: QueryClient) {
  await act(async () => {
    await queryClient.refetchQueries({ queryKey: instanceQuery().queryKey });
    // Query observers are notified in a scheduled batch after the refetch promise settles.
    await new Promise<void>((resolve) => notifyManager.schedule(resolve));
  });
}

test("sign-in links to the email reset form on a verified instance", async () => {
  // Arrange
  reportMode("verified");
  const { user } = open("/sign-in");

  // Act
  await user.click(await screen.findByRole("link", { name: "Forgot password?" }));

  // Assert
  expect(await screen.findByRole("button", { name: "Send reset link" })).toBeEnabled();
});

test("sign-in waits for a verified response before showing the reset link", async () => {
  // Arrange
  const lookup = holdModeLookup();

  // Act
  open("/sign-in");
  await lookup.started;

  // Assert
  try {
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
    expect(screen.queryByRole("link", { name: "Forgot password?" })).not.toBeInTheDocument();
  } finally {
    lookup.release();
  }
  await screen.findByRole("link", { name: "Forgot password?" });
});

test.for([
  ["an in-app destination", "/meetings/meeting?tab=transcript", "/meetings/meeting?tab=transcript"],
  ["an external destination", "//example.com", null],
  ["a destination with a fragment", "/meetings/meeting#token=synthetic", "/meetings/meeting"],
] as const)(
  "the reset detour preserves only the safe path for %s",
  async ([, target, expected]) => {
    // Arrange
    reportMode("verified");
    const { user } = open(`/sign-in?${new URLSearchParams({ redirect: target })}`);

    // Act
    await user.click(await screen.findByRole("link", { name: "Forgot password?" }));
    const resetTarget = new URLSearchParams(window.location.search).get("redirect");
    await user.click(await screen.findByRole("link", { name: "Back to sign in" }));

    // Assert
    await screen.findByRole("heading", { name: "Sign in" });
    expect([resetTarget, new URLSearchParams(window.location.search).get("redirect")]).toEqual([
      expected,
      expected,
    ]);
  },
);

test("a direct reset page visit does not send an unsafe destination back to sign-in", async () => {
  // Arrange
  reportMode("verified");
  const { user } = open(`/forgot-password?${new URLSearchParams({ redirect: "//example.com" })}`);

  // Act
  await user.click(await screen.findByRole("link", { name: "Back to sign in" }));

  // Assert
  await screen.findByRole("heading", { name: "Sign in" });
  expect(new URLSearchParams(window.location.search).has("redirect")).toBe(false);
});

test("sign-in offers no password reset on an invite-only instance", async () => {
  // Arrange
  reportMode("invite-only");
  const { queryClient } = open("/sign-in");

  // Act
  await waitFor(() =>
    expect(queryClient.getQueryState(instanceQuery().queryKey)?.status).toBe("success"),
  );

  // Assert
  expect(screen.queryByRole("link", { name: "Forgot password?" })).not.toBeInTheDocument();
});

test("sign-in stays usable when it cannot determine the instance mode", async () => {
  // Arrange
  failModeLookup();
  const { queryClient } = open("/sign-in");

  // Act
  await waitFor(() =>
    expect(queryClient.getQueryState(instanceQuery().queryKey)?.status).toBe("error"),
  );

  // Assert
  expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  expect(screen.queryByRole("link", { name: "Forgot password?" })).not.toBeInTheDocument();
});

test("an invite-only instance explains operator recovery to a direct visitor", async () => {
  // Arrange
  reportMode("invite-only");

  // Act
  open("/forgot-password");

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Ask your instance operator");
  expect(screen.queryByRole("button", { name: "Send reset link" })).not.toBeInTheDocument();
});

test("a direct visitor waits for the mode before they can request a reset", async () => {
  // Arrange
  const lookup = holdModeLookup();

  // Act
  open("/forgot-password");
  await lookup.started;

  // Assert
  try {
    expect(
      screen.getByRole("progressbar", { name: "Checking if password reset is available" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Email" })).not.toBeInTheDocument();
  } finally {
    lookup.release();
  }
  await screen.findByRole("textbox", { name: "Email" });
});

test("a direct visitor gets a way back when the mode lookup fails", async () => {
  // Arrange
  failModeLookup();
  const { user } = open("/forgot-password");
  await screen.findByText("Could not check if password reset is available.");

  // Act
  await user.click(screen.getByRole("link", { name: "Back to sign in" }));

  // Assert
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
});

test("an unauthorized response from the public mode lookup keeps the visitor on the reset page", async () => {
  // Arrange
  server.use(
    rawHttp.get("/api/v1/instance", () =>
      HttpResponse.json(errorBody("UNAUTHENTICATED", "Sign in required"), { status: 401 }),
    ),
  );

  // Act
  open("/forgot-password");

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not check if password reset is available.",
  );
});

test.for([EMAIL, "alice/ops@example.com", "mårten@example.com"])(
  "the email form sends %s and displays the API confirmation",
  async (email) => {
    // Arrange
    const requests: unknown[] = [];
    reportMode("verified");
    server.use(
      http.post("/api/v1/password-resets", async ({ request, response }) => {
        requests.push(await request.json());
        return response(202).json({ message: CONFIRMATION });
      }),
    );
    const { user } = open("/forgot-password");

    // Act
    await submitEmail(user, email);

    // Assert
    expect(await screen.findByRole("alert")).toHaveTextContent(CONFIRMATION);
    expect(requests).toEqual([{ email }]);
    expect(screen.queryByRole("textbox", { name: "Email" })).not.toBeInTheDocument();
  },
);

test("an invalid email is refused before it reaches the server", async () => {
  // Arrange
  const requests: unknown[] = [];
  reportMode("verified");
  server.use(
    http.post("/api/v1/password-resets", async ({ request, response }) => {
      requests.push(await request.json());
      return response(202).json({ message: CONFIRMATION });
    }),
  );
  const { user } = open("/forgot-password");

  // Act
  await submitEmail(user, "invalid-address");

  // Assert
  expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument();
  expect(requests).toHaveLength(0);
});

test("the form sends an address of 254 characters but refuses a longer one locally", async () => {
  // Arrange
  const prefix = `${"a".repeat(64)}@${"b".repeat(63)}.${"c".repeat(63)}.`;
  const email = `${prefix}${"d".repeat(57)}.com`;
  const longEmail = `${prefix}${"d".repeat(58)}.com`;
  const requests: unknown[] = [];
  reportMode("verified");
  server.use(
    http.post("/api/v1/password-resets", async ({ request, response }) => {
      requests.push(await request.json());
      return response(202).json({ message: CONFIRMATION });
    }),
  );
  const { user } = open("/forgot-password");
  const input = await screen.findByRole("textbox", { name: "Email" });
  const submit = screen.getByRole("button", { name: "Send reset link" });

  // Act
  fireEvent.change(input, { target: { value: longEmail } });
  await user.click(submit);
  await screen.findByText("Enter an email address with at most 254 characters");
  fireEvent.change(input, { target: { value: email } });
  await user.click(submit);

  // Assert
  await screen.findByText(CONFIRMATION);
  expect(requests).toEqual([{ email }]);
});

test("an accepted reset keeps its confirmation after a failed background mode check", async () => {
  // Arrange
  reportMode("verified");
  server.use(
    http.post("/api/v1/password-resets", ({ response }) =>
      response(202).json({ message: CONFIRMATION }),
    ),
  );
  const { user, queryClient } = open("/forgot-password");
  await submitEmail(user);
  await screen.findByText(CONFIRMATION);
  failModeLookup();

  // Act
  await refreshMode(queryClient);

  // Assert
  expect(screen.getByRole("alert")).toHaveTextContent(CONFIRMATION);
});

test("a pending request survives a failed mode refresh and ignores a second submit", async () => {
  // Arrange
  const pending = deferred();
  let requests = 0;
  reportMode("verified");
  server.use(
    http.post("/api/v1/password-resets", async ({ response }) => {
      requests += 1;
      await pending.promise;
      return response(202).json({ message: CONFIRMATION });
    }),
  );
  const { user, queryClient } = open("/forgot-password");
  await submitEmail(user);

  // Act
  try {
    failModeLookup();
    await refreshMode(queryClient);
    expect(screen.getByRole("button", { name: "Sending..." })).toBeDisabled();
    reportMode("verified");
    await refreshMode(queryClient);
    const button = screen.getByRole<HTMLButtonElement>("button", { name: "Sending..." });
    if (!button.form) throw new Error("The submit button has no form");
    expect(button).toBeDisabled();
    fireEvent.submit(button.form);
  } finally {
    pending.resolve();
  }

  // Assert
  await screen.findByText(CONFIRMATION);
  expect(requests).toBe(1);
});

test("a switch to invite-only during submission hides the stale reset form and link", async () => {
  // Arrange
  reportMode("verified");
  server.use(
    http.post("/api/v1/password-resets", ({ response }) =>
      response(403).json(errorBody("INVITE_ONLY_INSTANCE", "Invite-only instance")),
    ),
  );
  const { user } = open("/forgot-password");

  // Act
  await submitEmail(user);
  await screen.findByText("Ask your instance operator for a password reset link.");
  await user.click(screen.getByRole("link", { name: "Back to sign in" }));

  // Assert
  await screen.findByRole("heading", { name: "Sign in" });
  expect(screen.queryByRole("link", { name: "Forgot password?" })).not.toBeInTheDocument();
});

test("a temporary outage allows retry with the entered email", async () => {
  // Arrange
  let requests = 0;
  reportMode("verified");
  server.use(
    http.post("/api/v1/password-resets", ({ response }) => {
      requests += 1;
      return requests === 1
        ? response(503).json(errorBody("INTEGRATION_UNAVAILABLE", "Unavailable"))
        : response(202).json({ message: CONFIRMATION });
    }),
  );
  const { user } = open("/forgot-password");
  await submitEmail(user);
  await screen.findByText("Could not request a reset link. Try again.");

  // Act
  await user.click(screen.getByRole("button", { name: "Send reset link" }));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent(CONFIRMATION);
});

test("a server validation error is shown beside the email field", async () => {
  // Arrange
  const message = "Enter an email address accepted by this instance";
  reportMode("verified");
  server.use(
    http.post("/api/v1/password-resets", ({ response }) =>
      response(422).json({
        error: {
          ...errorBody("VALIDATION_ERROR", "Invalid address").error,
          details: [{ field: "email", message }],
        },
      }),
    ),
  );
  const { user } = open("/forgot-password");

  // Act
  await submitEmail(user);

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(screen.getByRole("textbox", { name: "Email" })).toHaveAccessibleDescription(message);
});
