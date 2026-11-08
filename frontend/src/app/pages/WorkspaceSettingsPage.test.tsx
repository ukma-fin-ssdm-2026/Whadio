import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { page, workspaceRead } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { WorkspaceSettingsPage } from "./WorkspaceSettingsPage";

function openSettings(changes: Partial<Schemas["WorkspaceRead"]>) {
  let invitationReads = 0;
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}", ({ response }) =>
      response(200).json(workspaceRead(changes)),
    ),
    http.get("/api/v1/workspaces/{workspace_id}/invitations", ({ response }) => {
      invitationReads += 1;
      return response(200).json(page([]));
    }),
  );
  renderWithProviders(<WorkspaceSettingsPage workspaceId="workspace" />);
  return () => invitationReads;
}

test.each(["owner", "moderator"] as const)("a %s can manage invitations", async (role) => {
  // Arrange
  openSettings({ my_role: role });

  // Act
  await screen.findByRole("heading", { name: "Workspace settings" });

  // Assert
  expect(screen.getByRole("heading", { name: "Invitations" })).toBeInTheDocument();
});

test("a Member has no invitation management", async () => {
  // Arrange
  const invitationReads = openSettings({ my_role: "member" });

  // Act
  await screen.findByRole("heading", { name: "Workspace settings" });

  // Assert
  expect(screen.queryByRole("heading", { name: "Invitations" })).not.toBeInTheDocument();
  expect(invitationReads()).toBe(0);
});

test("a personal workspace has no invitation management", async () => {
  // Arrange
  const invitationReads = openSettings({ is_personal: true, my_role: "owner" });

  // Act
  await screen.findByRole("heading", { name: "Workspace settings" });

  // Assert
  expect(screen.queryByRole("heading", { name: "Invitations" })).not.toBeInTheDocument();
  expect(invitationReads()).toBe(0);
});
