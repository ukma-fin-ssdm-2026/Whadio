import { screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { memberRead, page, workspaceRead } from "@/shared/testing/fixtures";
import { createTestQueryClient, TestProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { renderAtPath } from "../testing";
import { WorkspaceMembersPage } from "./WorkspaceMembersPage";

const MEMBER = memberRead();

function openMembers(changes: Partial<Schemas["WorkspaceRead"]>) {
  const reads = { members: 0, invitations: 0 };
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}", ({ response }) =>
      response(200).json(workspaceRead(changes)),
    ),
    http.get("/api/v1/workspaces/{workspace_id}/members", ({ response }) => {
      reads.members += 1;
      return response(200).json(page([MEMBER]));
    }),
    http.get("/api/v1/workspaces/{workspace_id}/invitations", ({ response }) => {
      reads.invitations += 1;
      return response(200).json(page([]));
    }),
  );
  renderAtPath(
    <TestProviders queryClient={createTestQueryClient()}>
      <WorkspaceMembersPage workspaceId="workspace" />
    </TestProviders>,
  );
  return reads;
}

test.each(["owner", "moderator"] as const)("a %s can manage invitations", async (role) => {
  // Arrange
  openMembers({ my_role: role });

  // Act
  await screen.findByRole("heading", { name: "Members" });

  // Assert
  expect(screen.getByRole("heading", { name: "Invitations" })).toBeInTheDocument();
});

test("a Member has no invitation management", async () => {
  // Arrange
  const reads = openMembers({ my_role: "member" });

  // Act
  await screen.findByRole("heading", { name: "Members" });

  // Assert
  expect(screen.queryByRole("heading", { name: "Invitations" })).not.toBeInTheDocument();
  expect(reads.invitations).toBe(0);
});

test("a personal workspace has no invitation management", async () => {
  // Arrange
  const reads = openMembers({ is_personal: true, my_role: "owner" });

  // Act
  await screen.findByRole("heading", { name: "Page not found" });

  // Assert
  expect(screen.queryByRole("heading", { name: "Invitations" })).not.toBeInTheDocument();
  expect(reads.invitations).toBe(0);
});

test("a Member sees the member list", async () => {
  // Arrange
  openMembers({ my_role: "member" });

  // Act
  const list = await screen.findByRole("list", { name: "Workspace members" });

  // Assert
  expect(within(list).getByText(MEMBER.name)).toBeInTheDocument();
});

test("a personal workspace is not found and requests no members", async () => {
  // Arrange
  const reads = openMembers({ is_personal: true, my_role: "owner" });

  // Act
  await screen.findByRole("heading", { name: "Page not found" });

  // Assert
  expect(reads.members).toBe(0);
});
