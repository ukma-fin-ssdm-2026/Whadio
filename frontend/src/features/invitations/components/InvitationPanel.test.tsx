import { screen, waitFor, within } from "@testing-library/react";
import { expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { errorBody, page } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { InvitationPanel } from "./InvitationPanel";

const LINK = "https://whadio.test/invitations/11111111-1111-4111-8111-111111111111#token=secret";
const INVITATION: Schemas["InvitationRead"] = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "member@example.test",
  role: "member",
  status: "pending",
  created_at: "2026-11-01T10:00:00Z",
  expires_at: "2026-11-08T10:00:00Z",
  link_active: true,
};

function serve(items: Schemas["InvitationRead"][] = [INVITATION]) {
  const created: unknown[] = [];
  const cancelled: string[] = [];
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/invitations", ({ response }) =>
      response(200).json(page(items)),
    ),
    http.post("/api/v1/workspaces/{workspace_id}/invitations", async ({ request, response }) => {
      created.push(await request.json());
      return response(201).json({ ...INVITATION, role: "moderator", link: LINK });
    }),
    http.post(
      "/api/v1/workspaces/{workspace_id}/invitations/{invitation_id}/cancel",
      ({ params, response }) => {
        cancelled.push(params.invitation_id);
        return response(200).json({ ...INVITATION, status: "cancelled" });
      },
    ),
  );
  return { cancelled, created };
}

test("lists pending invitations with their role and expiry", async () => {
  // Arrange
  serve();

  // Act
  renderWithProviders(<InvitationPanel workspaceId="workspace" />);

  // Assert
  const list = await screen.findByRole("list", { name: "Pending invitations" });
  expect(within(list).getByText("member@example.test")).toBeInTheDocument();
  expect(within(list).getByText(/Member · Expires/)).toBeInTheDocument();
});

test("submits only Member or Moderator as the invited role", async () => {
  // Arrange
  const { created } = serve([]);
  const { user } = renderWithProviders(<InvitationPanel workspaceId="workspace" />);
  await user.click(await screen.findByRole("button", { name: "Invite person" }));
  const dialog = screen.getByRole("dialog");
  await user.type(within(dialog).getByLabelText(/^Email address/), "moderator@example.test");
  await user.click(within(dialog).getByRole("combobox", { name: "Role" }));
  await user.click(screen.getByRole("option", { name: "Moderator" }));

  // Act
  await user.click(within(dialog).getByRole("button", { name: "Invite" }));

  // Assert
  await waitFor(() =>
    expect(created).toEqual([{ email: "moderator@example.test", role: "moderator" }]),
  );
});

test("shows an invite-only link only until its dialog closes", async () => {
  // Arrange
  serve([]);
  const { user } = renderWithProviders(<InvitationPanel workspaceId="workspace" />);
  await user.click(await screen.findByRole("button", { name: "Invite person" }));
  const dialog = screen.getByRole("dialog");
  await user.type(within(dialog).getByLabelText(/^Email address/), "member@example.test");
  await user.click(within(dialog).getByRole("button", { name: "Invite" }));
  await screen.findByDisplayValue(LINK);

  // Act
  await user.click(screen.getByRole("button", { name: "Done" }));
  await user.click(screen.getByRole("button", { name: "Invite person" }));

  // Assert
  expect(screen.queryByDisplayValue(LINK)).not.toBeInTheDocument();
  expect(screen.queryByText("secret")).not.toBeInTheDocument();
});

test("cancels a pending invitation only after confirmation", async () => {
  // Arrange
  const { cancelled } = serve();
  const { user } = renderWithProviders(<InvitationPanel workspaceId="workspace" />);
  await user.click(
    await screen.findByRole("button", { name: "Cancel invitation for member@example.test" }),
  );

  // Act
  await user.click(screen.getByRole("button", { name: "Cancel invitation" }));

  // Assert
  await waitFor(() => expect(cancelled).toEqual([INVITATION.id]));
});

test("loads and cancels an invitation on a later page", async () => {
  // Arrange
  const { cancelled } = serve();
  const older = { ...INVITATION, email: "older@example.test" };
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/invitations", ({ request, response }) => {
      const cursor = new URL(request.url).searchParams.get("cursor");
      return response(200).json(
        cursor === "older-page"
          ? page([older])
          : {
              items: [{ ...INVITATION, id: "newer", email: "newer@example.test" }],
              pagination: { limit: 100, next_cursor: "older-page", has_more: true },
            },
      );
    }),
  );
  const { user } = renderWithProviders(<InvitationPanel workspaceId="workspace" />);

  // Act
  await user.click(await screen.findByRole("button", { name: "Load more invitations" }));
  await user.click(
    await screen.findByRole("button", { name: "Cancel invitation for older@example.test" }),
  );
  await user.click(screen.getByRole("button", { name: "Cancel invitation" }));

  // Assert
  await waitFor(() => expect(cancelled).toEqual([older.id]));
});

test("creating an invitation refreshes the pending list", async () => {
  // Arrange
  let items: Schemas["InvitationRead"][] = [];
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/invitations", ({ response }) =>
      response(200).json(page(items)),
    ),
    http.post("/api/v1/workspaces/{workspace_id}/invitations", ({ response }) => {
      items = [INVITATION];
      return response(201).json({ ...INVITATION, link: LINK });
    }),
  );
  const { user } = renderWithProviders(<InvitationPanel workspaceId="workspace" />);
  await screen.findByText("No pending invitations");
  await user.click(screen.getByRole("button", { name: "Invite person" }));
  await user.type(screen.getByLabelText(/^Email address/), INVITATION.email);

  // Act
  await user.click(screen.getByRole("button", { name: "Invite" }));
  await user.click(await screen.findByRole("button", { name: "Done" }));

  // Assert
  expect(
    await screen.findByRole("button", { name: `Cancel invitation for ${INVITATION.email}` }),
  ).toBeInTheDocument();
});

test("cancellation refreshes the pending list", async () => {
  // Arrange
  let items = [INVITATION];
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/invitations", ({ response }) =>
      response(200).json(page(items)),
    ),
    http.post(
      "/api/v1/workspaces/{workspace_id}/invitations/{invitation_id}/cancel",
      ({ response }) => {
        items = [];
        return response(200).json({ ...INVITATION, status: "cancelled" });
      },
    ),
  );
  const { user } = renderWithProviders(<InvitationPanel workspaceId="workspace" />);
  await user.click(
    await screen.findByRole("button", { name: `Cancel invitation for ${INVITATION.email}` }),
  );

  // Act
  await user.click(screen.getByRole("button", { name: "Cancel invitation" }));

  // Assert
  expect(await screen.findByText("No pending invitations")).toBeInTheDocument();
});

test.each([
  [409, "ALREADY_MEMBER", "That person already belongs to this workspace"],
  [429, "INVITATION_COOLDOWN", "Wait before inviting this person again"],
] as const)("displays the create error for HTTP %i", async (status, code, message) => {
  // Arrange
  serve([]);
  server.use(
    http.post("/api/v1/workspaces/{workspace_id}/invitations", ({ response }) =>
      response(status).json(errorBody(code, message)),
    ),
  );
  const { user } = renderWithProviders(<InvitationPanel workspaceId="workspace" />);
  await user.click(await screen.findByRole("button", { name: "Invite person" }));
  await user.type(screen.getByLabelText(/^Email address/), INVITATION.email);

  // Act
  await user.click(screen.getByRole("button", { name: "Invite" }));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent(message);
});

test("displays the pending-list load error", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/invitations", ({ response }) =>
      response(403).json(errorBody("INSUFFICIENT_ROLE", "Cannot list invitations")),
    ),
  );

  // Act
  renderWithProviders(<InvitationPanel workspaceId="workspace" />);

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Cannot list invitations");
});

test("marks a pending invitation with an inactive link", async () => {
  // Arrange
  serve([{ ...INVITATION, link_active: false }]);

  // Act
  renderWithProviders(<InvitationPanel workspaceId="workspace" />);

  // Assert
  expect(await screen.findByText("Inactive")).toBeInTheDocument();
});

test("releases the one-time link from the mutation cache when the dialog closes", async () => {
  // Arrange
  serve([]);
  const { queryClient, user } = renderWithProviders(<InvitationPanel workspaceId="workspace" />);
  await user.click(await screen.findByRole("button", { name: "Invite person" }));
  await user.type(screen.getByLabelText(/^Email address/), INVITATION.email);
  await user.click(screen.getByRole("button", { name: "Invite" }));
  await screen.findByDisplayValue(LINK);

  // Act
  await user.click(screen.getByRole("button", { name: "Done" }));

  // Assert
  await waitFor(() =>
    expect(
      queryClient
        .getMutationCache()
        .getAll()
        .map(({ state }) => state.data),
    ).not.toContainEqual(expect.objectContaining({ link: LINK })),
  );
});

const ALREADY_ANSWERED = "This invitation has already been answered";

async function openStaleCancellation() {
  let items = [INVITATION];
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/invitations", ({ response }) =>
      response(200).json(page(items)),
    ),
    http.post(
      "/api/v1/workspaces/{workspace_id}/invitations/{invitation_id}/cancel",
      ({ response }) => {
        items = [];
        return response(409).json(errorBody("INVITATION_NOT_PENDING", ALREADY_ANSWERED));
      },
    ),
  );
  const { user } = renderWithProviders(<InvitationPanel workspaceId="workspace" />);
  await user.click(
    await screen.findByRole("button", { name: `Cancel invitation for ${INVITATION.email}` }),
  );
  return user;
}

test("displays the error when cancelling an already answered invitation", async () => {
  // Arrange
  const user = await openStaleCancellation();

  // Act
  await user.click(screen.getByRole("button", { name: "Cancel invitation" }));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent(ALREADY_ANSWERED);
});

test("refreshes the pending list when cancellation finds an already answered invitation", async () => {
  // Arrange
  const user = await openStaleCancellation();

  // Act
  await user.click(screen.getByRole("button", { name: "Cancel invitation" }));

  // Assert
  expect(await screen.findByText("No pending invitations")).toBeInTheDocument();
});
