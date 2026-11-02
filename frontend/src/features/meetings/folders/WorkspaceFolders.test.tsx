import { screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { errorBody } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { WorkspaceFolders } from "./WorkspaceFolders";

const DEFAULT_FOLDER: Schemas["FolderRead"] = {
  id: "default",
  name: "General",
  is_default: true,
  meeting_count: 3,
};
const PLANNING_FOLDER: Schemas["FolderRead"] = {
  id: "planning",
  name: "Planning",
  is_default: false,
  meeting_count: 2,
};
const FOLDERS = [DEFAULT_FOLDER, PLANNING_FOLDER];

function renderFolders(role: Schemas["Role"] = "owner") {
  return renderWithProviders(
    <WorkspaceFolders
      workspaceId="workspace"
      role={role}
      folders={FOLDERS}
      selectedFolderId={null}
      loading={false}
      onSelect={() => {}}
    />,
  );
}

async function openPlanningMenu() {
  const user = renderFolders().user;
  await user.click(screen.getByRole("button", { name: "Manage Planning" }));
  return user;
}

test("a member is not offered folder creation", () => {
  // Act
  renderFolders("member");

  // Assert
  expect(screen.queryByRole("button", { name: "New folder" })).not.toBeInTheDocument();
});

test("a member is not offered folder management", () => {
  // Act
  renderFolders("member");

  // Assert
  expect(screen.queryByRole("button", { name: /Manage/ })).not.toBeInTheDocument();
});

test("a moderator is offered folder creation", () => {
  // Act
  renderFolders("moderator");

  // Assert
  expect(screen.getByRole("button", { name: "New folder" })).toBeInTheDocument();
});

test("an owner can create a folder", async () => {
  // Arrange
  const bodies: unknown[] = [];
  server.use(
    http.post("/api/v1/workspaces/{workspace_id}/folders", async ({ request, response }) => {
      bodies.push(await request.json());
      return response(201).json({
        id: "research",
        name: "Research",
        is_default: false,
        meeting_count: 0,
      });
    }),
  );
  const { user } = renderFolders();

  // Act
  await user.click(screen.getByRole("button", { name: "New folder" }));
  await user.type(screen.getByLabelText("Folder name"), "Research");
  await user.click(screen.getByRole("button", { name: "Save" }));

  // Assert
  expect(bodies).toEqual([{ name: "Research" }]);
});

test("an owner can rename a folder", async () => {
  // Arrange
  const bodies: unknown[] = [];
  server.use(
    http.patch(
      "/api/v1/workspaces/{workspace_id}/folders/{folder_id}",
      async ({ request, response }) => {
        bodies.push(await request.json());
        return response(200).json({ ...PLANNING_FOLDER, name: "Roadmap" });
      },
    ),
  );
  const user = await openPlanningMenu();

  // Act
  await user.click(screen.getByRole("menuitem", { name: "Rename" }));
  await user.clear(screen.getByLabelText("Folder name"));
  await user.type(screen.getByLabelText("Folder name"), "Roadmap");
  await user.click(screen.getByRole("button", { name: "Save" }));

  // Assert
  expect(bodies).toEqual([{ name: "Roadmap" }]);
});

test("the default folder cannot be deleted", async () => {
  // Arrange
  const { user } = renderFolders();

  // Act
  await user.click(screen.getByRole("button", { name: "Manage General" }));

  // Assert
  expect(screen.queryByRole("menuitem", { name: "Delete" })).not.toBeInTheDocument();
});

test("folder deletion explains where its meetings go", async () => {
  // Arrange
  const user = await openPlanningMenu();

  // Act
  await user.click(screen.getByRole("menuitem", { name: "Delete" }));

  // Assert
  expect(
    screen.getByText(/meetings in this folder will move to the default folder/i),
  ).toBeVisible();
});

test("cancelling folder deletion sends no request", async () => {
  // Arrange
  const remove = vi.fn();
  server.use(
    http.delete("/api/v1/workspaces/{workspace_id}/folders/{folder_id}", () => {
      remove();
    }),
  );
  const user = await openPlanningMenu();
  await user.click(screen.getByRole("menuitem", { name: "Delete" }));

  // Act
  await user.click(screen.getByRole("button", { name: "Cancel" }));

  // Assert
  expect(remove).not.toHaveBeenCalled();
});

test("deleted folders can be restored with Undo", async () => {
  // Arrange
  const restore = vi.fn();
  server.use(
    http.delete("/api/v1/workspaces/{workspace_id}/folders/{folder_id}", ({ response }) =>
      response(204).empty(),
    ),
    http.post("/api/v1/workspaces/{workspace_id}/folders/{folder_id}/restore", ({ response }) => {
      restore();
      return response(200).json(PLANNING_FOLDER);
    }),
  );
  const user = await openPlanningMenu();
  await user.click(screen.getByRole("menuitem", { name: "Delete" }));
  await user.click(screen.getByRole("button", { name: "Delete folder" }));

  // Act
  await user.click(await screen.findByRole("button", { name: "Undo" }));

  // Assert
  expect(restore).toHaveBeenCalledOnce();
});

test("the folder deletion notice is centred", async () => {
  // Arrange
  server.use(
    http.delete("/api/v1/workspaces/{workspace_id}/folders/{folder_id}", ({ response }) =>
      response(204).empty(),
    ),
  );
  const user = await openPlanningMenu();
  await user.click(screen.getByRole("menuitem", { name: "Delete" }));

  // Act
  await user.click(screen.getByRole("button", { name: "Delete folder" }));

  // Assert
  expect(screen.getByText(/folder deleted/i).closest(".MuiSnackbar-root")).toHaveClass(
    "MuiSnackbar-anchorOriginBottomCenter",
  );
});

test.for([
  ["FOLDER_EXISTS", /folder with this name already exists/i],
  ["FOLDER_RECOVERY_CONFLICT", /meetings have changed since deletion/i],
] as const)("a %s restore conflict is explained", async ([code, message]) => {
  // Arrange
  server.use(
    http.delete("/api/v1/workspaces/{workspace_id}/folders/{folder_id}", ({ response }) =>
      response(204).empty(),
    ),
    http.post("/api/v1/workspaces/{workspace_id}/folders/{folder_id}/restore", ({ response }) =>
      response(409).json(errorBody(code, "Conflict")),
    ),
  );
  const user = await openPlanningMenu();
  await user.click(screen.getByRole("menuitem", { name: "Delete" }));
  await user.click(screen.getByRole("button", { name: "Delete folder" }));

  // Act
  await user.click(await screen.findByRole("button", { name: "Undo" }));

  // Assert
  expect(await screen.findByText(message)).toBeVisible();
});
