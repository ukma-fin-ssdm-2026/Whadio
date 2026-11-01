import { screen, waitFor } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { SignInForm } from "./SignInForm";

const USER: Schemas["UserRead"] = {
  id: "member",
  email: "member@example.com",
  name: "Demo Member",
  is_administrator: false,
  created_at: "2026-10-25T10:00:00Z",
};

type ErrorEnvelope = Schemas["ErrorResponse"];

const errorEnvelope = (
  code: ErrorEnvelope["error"]["code"],
  message: string,
  details: ErrorEnvelope["error"]["details"] = [],
): ErrorEnvelope => ({ error: { code, message, details, request_id: "req_1" } });

function answerSignIn(status: 201 | 401 | 422, body?: ErrorEnvelope) {
  const requests: unknown[] = [];
  server.use(
    http.post("/api/v1/sessions", async ({ request, response }) => {
      requests.push(await request.json());
      if (status === 201) {
        return response(201).json({ kind: "browser", expires_at: USER.created_at, user: USER });
      }
      return response(status).json(body ?? errorEnvelope("INTERNAL_ERROR", "Failed"));
    }),
  );
  return requests;
}

function renderForm(externalError?: string) {
  const onSignedIn = vi.fn();
  const rendered = renderWithProviders(
    <SignInForm onSignedIn={onSignedIn} externalError={externalError} />,
  );
  return { ...rendered, onSignedIn };
}

async function submit(email: string, password: string) {
  const { user, onSignedIn } = renderForm();
  if (email) await user.type(screen.getByLabelText(/^Email/), email);
  if (password) await user.type(screen.getByLabelText(/^Password/), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  return onSignedIn;
}

describe("an empty form", () => {
  test("asks for the email address", async () => {
    // Act
    await submit("", "");

    // Assert
    expect(screen.getByLabelText(/^Email/)).toHaveAccessibleDescription("Enter your email address");
  });

  test("asks for the password", async () => {
    // Act
    await submit("", "");

    // Assert
    expect(screen.getByLabelText(/^Password/)).toHaveAccessibleDescription("Enter your password");
  });

  test("is not sent", async () => {
    // Arrange
    const requests = answerSignIn(201);

    // Act
    await submit("", "");

    // Assert
    expect(requests).toEqual([]);
  });
});

test("a malformed email address asks for a valid one", async () => {
  // Act
  await submit("member", "test-password");

  // Assert
  expect(screen.getByLabelText(/^Email/)).toHaveAccessibleDescription(
    "Enter a valid email address",
  );
});

test("wrong credentials show the server's message", async () => {
  // Arrange
  answerSignIn(
    401,
    errorEnvelope("INVALID_CREDENTIALS", "Unknown email address or wrong password"),
  );

  // Act
  await submit("member@example.com", "wrong-password");

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Unknown email address or wrong password",
  );
});

test("a rejected field shows the server's reason on that field", async () => {
  // Arrange
  answerSignIn(
    422,
    errorEnvelope("VALIDATION_ERROR", "Request contains invalid fields", [
      { field: "email", message: "The domain does not accept email" },
    ]),
  );

  // Act
  await submit("member@example.invalid", "test-password");

  // Assert
  await waitFor(() =>
    expect(screen.getByLabelText(/^Email/)).toHaveAccessibleDescription(
      "The domain does not accept email",
    ),
  );
});

test("a successful sign-in hands over the user", async () => {
  // Arrange
  answerSignIn(201);

  // Act
  const onSignedIn = await submit("member@example.com", "test-password");

  // Assert
  await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith(USER));
});

test("shows an error raised outside the form", () => {
  // Act
  renderForm("Could not load your workspaces");

  // Assert
  expect(screen.getByRole("alert")).toHaveTextContent("Could not load your workspaces");
});
