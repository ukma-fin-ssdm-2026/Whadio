import { screen, waitFor, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { memberRead, page, workspaceRead } from "@/shared/testing/fixtures";
import { createTestQueryClient, TestProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { renderAtPath } from "../testing";
import { WorkspaceMembersPage } from "./WorkspaceMembersPage";

const MEMBER = memberRead();

function openMembers(changes: Partial<Schemas["WorkspaceRead"]>, members = [MEMBER]) {
  const reads = { members: 0, invitations: 0 };
  server.use(
    http.get("/api/v1/users/me", ({ response }) =>
      response(200).json({
        id: MEMBER.user_id,
        email: MEMBER.email,
        name: MEMBER.name,
        is_administrator: false,
        created_at: MEMBER.joined_at,
      }),
    ),
    http.get("/api/v1/workspaces/{workspace_id}", ({ response }) =>
      response(200).json(workspaceRead(changes)),
    ),
    http.get("/api/v1/workspaces/{workspace_id}/members", ({ response }) => {
      reads.members += 1;
      return response(200).json(page(members));
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

async function demoteYourself() {
  const workspace: Partial<Schemas["WorkspaceRead"]> = { my_role: "moderator" };
  const members = [memberRead({ role: "moderator" })];
  server.use(
    http.patch(
      "/api/v1/workspaces/{workspace_id}/members/{user_id}",
      async ({ request, response }) => {
        const { role } = await request.json();
        workspace.my_role = role;
        members.splice(0, 1, memberRead({ role }));
        return response(200).json(memberRead({ role }));
      },
    ),
  );
  const user = userEvent.setup();
  const reads = openMembers(workspace, members);
  await user.click(await screen.findByRole("combobox", { name: `Role of ${MEMBER.name}` }));
  await user.click(screen.getByRole("option", { name: "Member" }));
  await user.click(screen.getByRole("button", { name: "Change role" }));
  return reads;
}

test("demoting yourself leaves no member or invitation management", async () => {
  // Act
  await demoteYourself();

  // Assert
  await waitFor(() =>
    expect([
      screen.queryByRole("heading", { name: "Invitations" }),
      screen.queryByRole("combobox"),
    ]).toEqual([null, null]),
  );
});

test("demoting yourself asks nothing more of the invitations", async () => {
  // Act
  const reads = await demoteYourself();
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

  // Assert
  expect(reads.invitations).toBe(1);
});
