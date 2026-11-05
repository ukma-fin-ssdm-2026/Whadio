import { screen, waitFor, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { errorBody } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { InvitationRedemption } from "./InvitationRedemption";

const ID = "11111111-1111-4111-8111-111111111111";
const TOKEN = "fragment-secret";
const PREVIEW: Schemas["PreviewRead"] = {
  workspace_id: "22222222-2222-4222-8222-222222222222",
  workspace_name: "Research Team",
  email: "invited@example.test",
  role: "member",
  account_exists: true,
};
const USER: Schemas["UserRead"] = {
  id: "33333333-3333-4333-8333-333333333333",
  email: PREVIEW.email,
  name: "Invited Person",
  is_administrator: false,
  created_at: "2026-11-05T10:00:00Z",
};
const MEMBERSHIP: Schemas["MembershipRead"] = {
  user_id: USER.id,
  workspace_id: PREVIEW.workspace_id,
  role: "member",
  joined_at: "2026-11-05T10:00:00Z",
};

function validationError(field: string, message: string) {
  return {
    error: {
      code: "VALIDATION_ERROR" as const,
      message: "Invalid fields",
      details: [{ field, message }],
      request_id: "request",
    },
  };
}

function renderInvitation(currentUser: Schemas["UserRead"] | null | undefined = null) {
  const onJoined = vi.fn(async () => undefined);
  const onRequestSignIn = vi.fn();
  const onUseDifferentAccount = vi.fn(async () => undefined);
  const rendered = renderWithProviders(
    <InvitationRedemption
      id={ID}
      token={TOKEN}
      currentUser={currentUser}
      termsHref="/terms"
      onRequestSignIn={onRequestSignIn}
      onUseDifferentAccount={onUseDifferentAccount}
      onJoined={onJoined}
    />,
  );
  return { ...rendered, onJoined, onRequestSignIn, onUseDifferentAccount };
}

function servePreview(preview: Schemas["PreviewRead"] = PREVIEW) {
  server.use(
    http.post("/api/v1/invitations/{invitation_id}/preview", ({ response }) =>
      response(200).json(preview),
    ),
  );
}

test("previews with the fragment token only in the POST body", async () => {
  // Arrange
  const requests: { body: unknown; url: string }[] = [];
  server.use(
    http.post("/api/v1/invitations/{invitation_id}/preview", async ({ request, response }) => {
      requests.push({ body: await request.json(), url: request.url });
      return response(200).json(PREVIEW);
    }),
  );

  // Act
  renderInvitation();
  await screen.findByRole("heading", { name: "Join Research Team" });

  // Assert
  expect(requests).toEqual([
    { body: { token: TOKEN }, url: `http://localhost:3000/api/v1/invitations/${ID}/preview` },
  ]);
});

test("renders a generic invalid-link state for LINK_INVALID", async () => {
  // Arrange
  server.use(
    http.post("/api/v1/invitations/{invitation_id}/preview", ({ response }) =>
      response(404).json(errorBody("LINK_INVALID", "Expired secret")),
    ),
  );

  // Act
  renderInvitation();

  // Assert
  expect(
    await screen.findByRole("heading", { name: "Invitation unavailable" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("alert")).not.toHaveTextContent("Expired secret");
  expect(document.body).not.toHaveTextContent(TOKEN);
});

test("offers sign-in when the invited address already has an account", async () => {
  // Arrange
  servePreview();
  const { onRequestSignIn, user } = renderInvitation();

  // Act
  await user.click(await screen.findByRole("button", { name: "Sign in" }));

  // Assert
  expect(onRequestSignIn).toHaveBeenCalledOnce();
});

test("a matching signed-in account accepts the invitation", async () => {
  // Arrange
  servePreview();
  server.use(
    http.post("/api/v1/invitations/{invitation_id}/accept", ({ response }) =>
      response(200).json(MEMBERSHIP),
    ),
  );
  const { onJoined, user } = renderInvitation(USER);

  // Act
  await user.click(await screen.findByRole("button", { name: "Accept invitation" }));

  // Assert
  await waitFor(() => expect(onJoined).toHaveBeenCalledWith(PREVIEW.workspace_id));
});

test("a wrong signed-in account is refused before acceptance", async () => {
  // Arrange
  servePreview();
  const { onUseDifferentAccount, user } = renderInvitation({
    ...USER,
    email: "someone-else@example.test",
  });

  // Act
  await user.click(await screen.findByRole("button", { name: "Use a different account" }));

  // Assert
  expect(onUseDifferentAccount).toHaveBeenCalledOnce();
  expect(screen.queryByRole("button", { name: "Accept invitation" })).not.toBeInTheDocument();
});

test("EMAIL_MISMATCH does not reveal another account", async () => {
  // Arrange
  servePreview();
  server.use(
    http.post("/api/v1/invitations/{invitation_id}/accept", ({ response }) =>
      response(403).json(errorBody("EMAIL_MISMATCH", "Private mismatch detail")),
    ),
  );
  const { user } = renderInvitation(USER);

  // Act
  await user.click(await screen.findByRole("button", { name: "Accept invitation" }));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("belongs to a different account");
  expect(screen.getByRole("alert")).not.toHaveTextContent("Private mismatch detail");
});

test("registers an invited address without an account", async () => {
  // Arrange
  servePreview({ ...PREVIEW, account_exists: false });
  server.use(
    http.post("/api/v1/invitations/{invitation_id}/register", ({ response }) =>
      response(201).json({ user: USER, membership: MEMBERSHIP }),
    ),
  );
  const { onJoined, user } = renderInvitation();
  await user.type(await screen.findByLabelText(/^Name/), "Invited Person");
  await user.type(screen.getByLabelText(/^Password/), "StrongPassword1");
  await user.click(screen.getByRole("checkbox"));

  // Act
  await user.click(screen.getByRole("button", { name: "Create account and join" }));

  // Assert
  await waitFor(() => expect(onJoined).toHaveBeenCalledWith(PREVIEW.workspace_id, USER));
});

test("shows registration validation errors beside their field", async () => {
  // Arrange
  servePreview({ ...PREVIEW, account_exists: false });
  server.use(
    http.post("/api/v1/invitations/{invitation_id}/register", ({ response }) =>
      response(422).json(validationError("password", "Choose another password")),
    ),
  );
  const { user } = renderInvitation();
  await user.type(await screen.findByLabelText(/^Name/), "Invited Person");
  await user.type(screen.getByLabelText(/^Password/), "StrongPassword1");
  await user.click(screen.getByRole("checkbox"));

  // Act
  await user.click(screen.getByRole("button", { name: "Create account and join" }));

  // Assert
  await waitFor(() =>
    expect(screen.getByLabelText(/^Password/)).toHaveAccessibleDescription(
      "Choose another password",
    ),
  );
});

test("ACCOUNT_EXISTS switches registration to sign-in", async () => {
  // Arrange
  servePreview({ ...PREVIEW, account_exists: false });
  server.use(
    http.post("/api/v1/invitations/{invitation_id}/register", ({ response }) =>
      response(409).json(errorBody("ACCOUNT_EXISTS", "Private account detail")),
    ),
  );
  const { user } = renderInvitation();
  await user.type(await screen.findByLabelText(/^Name/), "Invited Person");
  await user.type(screen.getByLabelText(/^Password/), "StrongPassword1");
  await user.click(screen.getByRole("checkbox"));

  // Act
  await user.click(screen.getByRole("button", { name: "Create account and join" }));

  // Assert
  expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  expect(screen.getByRole("alert")).not.toHaveTextContent("Private account detail");
});

test("any link holder can decline after confirmation", async () => {
  // Arrange
  servePreview();
  server.use(
    http.post("/api/v1/invitations/{invitation_id}/decline", ({ response }) =>
      response(200).json({
        id: ID,
        email: PREVIEW.email,
        role: PREVIEW.role,
        status: "declined",
        created_at: "2026-11-01T10:00:00Z",
        expires_at: "2026-11-08T10:00:00Z",
        link_active: false,
      }),
    ),
  );
  const { user } = renderInvitation();
  await user.click(await screen.findByRole("button", { name: "Decline invitation" }));

  // Act
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Decline invitation" }),
  );

  // Assert
  expect(await screen.findByRole("heading", { name: "Invitation declined" })).toBeInTheDocument();
});
