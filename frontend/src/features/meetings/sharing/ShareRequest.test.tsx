import { screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { errorBody } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { ShareRequest } from "./ShareRequest";

const SHARE_ID = "11111111-1111-4111-8111-111111111111";
const TOKEN = "fragment-secret";
const USER: Schemas["UserRead"] = {
  id: "33333333-3333-4333-8333-333333333333",
  email: "recipient@example.test",
  name: "Recipient",
  is_administrator: false,
  created_at: "2026-11-05T10:00:00Z",
};
const PENDING: Schemas["RequestRead"] = {
  id: "44444444-4444-4444-8444-444444444444",
  requester_user_id: USER.id,
  name: USER.name,
  email: USER.email,
  status: "pending",
};

type Answer =
  | { status: 201; body: Schemas["RequestRead"] }
  | { status: 401 | 404 | 409; body: ReturnType<typeof errorBody> };

const CREATED: Answer = { status: 201, body: PENDING };

function refused(status: 401 | 404 | 409, code: Schemas["ErrorCode"]): Answer {
  return { status, body: errorBody(code, "Refused") };
}

function serveRequest(answer: Answer) {
  const sent: { path: string; body: unknown }[] = [];
  server.use(
    http.post(
      "/api/v1/shares/{share_id}/access-requests",
      async ({ request, params, response }) => {
        sent.push({ path: params.share_id, body: await request.json() });
        return answer.status === 201
          ? response(201).json(answer.body)
          : response.untyped(Response.json(answer.body, { status: answer.status }));
      },
    ),
  );
  return sent;
}

function renderRequest(
  changes: Partial<Parameters<typeof ShareRequest>[0]> = {},
): ReturnType<typeof renderWithProviders> {
  return renderWithProviders(
    <ShareRequest
      shareId={SHARE_ID}
      token={TOKEN}
      currentUser={USER}
      onRequestSignIn={() => {}}
      onSessionExpired={() => {}}
      onOpen={() => {}}
      {...changes}
    />,
  );
}

async function requestAccess(answer: Answer) {
  const sent = serveRequest(answer);
  const { user } = renderRequest();
  await user.click(screen.getByRole("button", { name: "Request access" }));
  return sent;
}

test("a signed-out person is asked to sign in and sees no request button", () => {
  // Arrange
  const onRequestSignIn = vi.fn();

  // Act
  renderRequest({ currentUser: null, onRequestSignIn });

  // Assert
  expect(screen.queryByRole("button", { name: "Request access" })).not.toBeInTheDocument();
});

test("signing in from a share link opens the sign-in form", async () => {
  // Arrange
  const onRequestSignIn = vi.fn();
  const { user } = renderRequest({ currentUser: null, onRequestSignIn });

  // Act
  await user.click(screen.getByRole("button", { name: "Sign in" }));

  // Assert
  expect(onRequestSignIn).toHaveBeenCalledOnce();
});

test("the token goes only in the request body", async () => {
  // Arrange
  // Act
  const sent = await requestAccess(CREATED);

  // Assert
  await waitFor(() => expect(sent).toEqual([{ path: SHARE_ID, body: { token: TOKEN } }]));
});

test("a sent request says the creator was asked to approve", async () => {
  // Arrange
  // Act
  await requestAccess(CREATED);

  // Assert
  expect(await screen.findByRole("heading", { name: "Access requested" })).toBeInTheDocument();
});

test("asking twice says the request already exists", async () => {
  // Arrange
  // Act
  await requestAccess(refused(409, "ACCESS_REQUEST_EXISTS"));

  // Assert
  expect(await screen.findByText(/already asked for access/)).toBeInTheDocument();
});

test("an account with access is offered its shared meetings", async () => {
  // Arrange
  // Act
  await requestAccess(refused(409, "ALREADY_HAS_ACCESS"));

  // Assert
  expect(
    await screen.findByRole("heading", { name: "You already have access" }),
  ).toBeInTheDocument();
});

test("an unusable link says it cannot be used", async () => {
  // Arrange
  // Act
  await requestAccess(refused(404, "LINK_INVALID"));

  // Assert
  expect(
    await screen.findByRole("heading", { name: "Share link unavailable" }),
  ).toBeInTheDocument();
});

test("a link without a token is unavailable before any request", () => {
  // Arrange
  const sent = serveRequest(CREATED);

  // Act
  renderRequest({ token: null });

  // Assert
  expect(screen.getByRole("heading", { name: "Share link unavailable" })).toBeInTheDocument();
  expect(sent).toEqual([]);
});

test("an expired session sends the person to sign in again", async () => {
  // Arrange
  const onSessionExpired = vi.fn();
  serveRequest(refused(401, "UNAUTHENTICATED"));
  const { user } = renderRequest({ onSessionExpired });

  // Act
  await user.click(screen.getByRole("button", { name: "Request access" }));

  // Assert
  await waitFor(() => expect(onSessionExpired).toHaveBeenCalledOnce());
});
