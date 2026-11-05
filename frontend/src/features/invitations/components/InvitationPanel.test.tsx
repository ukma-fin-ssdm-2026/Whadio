import { screen, waitFor, within } from "@testing-library/react";
import { expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { page } from "@/shared/testing/fixtures";
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
