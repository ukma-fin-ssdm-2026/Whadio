import { screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { errorBody, page } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { requestShareAccess } from "../api/shares";
import { ShareRequest } from "./ShareRequest";

vi.mock("../api/shares", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/shares")>();
  return { ...actual, requestShareAccess: vi.fn(actual.requestShareAccess) };
});

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
      onUseDifferentAccount={() => {}}
      onOpen={() => {}}
      onOpenMeetings={() => {}}
      {...changes}
    />,
  );
}

function serveReceived(shareIds: string[], pageSize = 100) {
  const shares = shareIds.map((id) => ({
    id,
    redact_speaker_names: false,
    recipient_user_id: USER.id,
    revoked_at: null,
    created_at: "2026-11-17T10:00:00Z",
  }));
  server.use(
    http.get("/api/v1/users/me/shares", ({ request, response }) => {
      const start = Number(new URL(request.url).searchParams.get("cursor") ?? 0);
      const end = start + pageSize;
      return response(200).json(
        page(shares.slice(start, end), end < shares.length ? String(end) : null),
      );
    }),
  );
}

async function requestAccess(answer: Answer) {
  const sent = serveRequest(answer);
  const { user } = renderRequest();
  await user.click(screen.getByRole("button", { name: "Request access" }));
  return sent;
}

test("a signed-out person is asked to sign in", () => {
  // Act
  renderRequest({ currentUser: null });

  // Assert
  expect(screen.getByText("Sign in to ask for access.")).toBeInTheDocument();
});

test("a signed-out person sees no request button", () => {
  // Act
  renderRequest({ currentUser: null });

  // Assert
  expect(screen.queryByRole("button", { name: "Request access" })).not.toBeInTheDocument();
});

test("a failed account check says why and offers a retry", async () => {
  // Arrange
  const onRetrySession = vi.fn();
  const { user } = renderRequest({
    currentUser: undefined,
    sessionError: "Account check failed",
    onRetrySession,
  });

  // Act
  await user.click(screen.getByRole("button", { name: "Retry account check" }));

  // Assert
  expect(onRetrySession).toHaveBeenCalledOnce();
});

test("a failed account check shows its message", () => {
  // Act
  renderRequest({ currentUser: undefined, sessionError: "Account check failed" });

  // Assert
  expect(screen.getByRole("alert")).toHaveTextContent("Account check failed");
});

test("a failed account check still offers to sign in", async () => {
  // Arrange
  const onRequestSignIn = vi.fn();
  const { user } = renderRequest({
    currentUser: undefined,
    sessionError: "Account check failed",
    onRequestSignIn,
  });

  // Act
  await user.click(screen.getByRole("button", { name: "Sign in" }));

  // Assert
  expect(onRequestSignIn).toHaveBeenCalledOnce();
});

test("a signed-in person can switch to a different account", async () => {
  // Arrange
  const onUseDifferentAccount = vi.fn();
  const { user } = renderRequest({ onUseDifferentAccount });

  // Act
  await user.click(screen.getByRole("button", { name: "Use a different account" }));

  // Assert
  expect(onUseDifferentAccount).toHaveBeenCalledOnce();
});

test("a share id that is not an id is unavailable before any request", () => {
  // Arrange
  const sent = serveRequest(CREATED);

  // Act
  renderRequest({ shareId: "not-a-share" });

  // Assert
  expect(screen.getByRole("heading", { name: "Share link unavailable" })).toBeInTheDocument();
  expect(sent).toEqual([]);
});

test("a refused request shows the server's message", async () => {
  // Arrange
  // Act
  await requestAccess(refused(409, "VALIDATION_ERROR"));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Refused");
});

test("a request that fails without an API error shows a generic message", async () => {
  // Arrange
  vi.mocked(requestShareAccess).mockRejectedValueOnce(new Error("boom"));
  const { user } = renderRequest();

  // Act
  await user.click(screen.getByRole("button", { name: "Request access" }));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not request access.");
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

test("an account with access says so", async () => {
  // Arrange
  serveReceived([]);

  // Act
  await requestAccess(refused(409, "ALREADY_HAS_ACCESS"));

  // Assert
  expect(
    await screen.findByRole("heading", { name: "You already have access" }),
  ).toBeInTheDocument();
});

test("an account the share is bound to is offered the shared meeting", async () => {
  // Arrange
  serveReceived(["22222222-2222-4222-8222-222222222222", SHARE_ID]);
  const onOpen = vi.fn();
  const sent = serveRequest(refused(409, "ALREADY_HAS_ACCESS"));
  const { user } = renderRequest({ onOpen });
  await user.click(screen.getByRole("button", { name: "Request access" }));
  await waitFor(() => expect(sent).toHaveLength(1));

  // Act
  await user.click(await screen.findByRole("button", { name: "Open the shared meeting" }));

  // Assert
  expect(onOpen).toHaveBeenCalledOnce();
});

test("a bound share on a later page is still found", async () => {
  // Arrange
  serveReceived(["22222222-2222-4222-8222-222222222222", SHARE_ID], 1);
  const sent = serveRequest(refused(409, "ALREADY_HAS_ACCESS"));
  const { user } = renderRequest();
  await user.click(screen.getByRole("button", { name: "Request access" }));
  await waitFor(() => expect(sent).toHaveLength(1));

  // Act
  const open = await screen.findByRole("button", { name: "Open the shared meeting" });

  // Assert
  expect(open).toBeInTheDocument();
});

test("a workspace member whose share is not bound to them is sent to Meetings", async () => {
  // Arrange
  serveReceived([]);
  const onOpenMeetings = vi.fn();
  const sent = serveRequest(refused(409, "ALREADY_HAS_ACCESS"));
  const { user } = renderRequest({ onOpenMeetings });
  await user.click(screen.getByRole("button", { name: "Request access" }));
  await waitFor(() => expect(sent).toHaveLength(1));

  // Act
  await user.click(await screen.findByRole("button", { name: "Meetings" }));

  // Assert
  expect(onOpenMeetings).toHaveBeenCalledOnce();
});

test("a workspace member is told the meeting is in their workspace", async () => {
  // Arrange
  serveReceived([]);

  // Act
  await requestAccess(refused(409, "ALREADY_HAS_ACCESS"));

  // Assert
  expect(await screen.findByText(/in your workspace/)).toBeInTheDocument();
});

test("a failed shares check says why", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/users/me/shares", ({ response }) =>
      response(503).json(errorBody("INTERNAL_ERROR", "Shares unavailable")),
    ),
  );

  // Act
  await requestAccess(refused(409, "ALREADY_HAS_ACCESS"));

  // Assert
  expect(await screen.findByText("Shares unavailable")).toBeInTheDocument();
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
