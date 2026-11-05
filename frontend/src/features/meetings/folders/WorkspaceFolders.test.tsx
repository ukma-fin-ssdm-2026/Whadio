import { screen, waitFor, waitForElementToBeRemoved } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
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

function serveCreate() {
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
  return bodies;
}

function refuseCreate() {
  server.use(
    http.post("/api/v1/workspaces/{workspace_id}/folders", ({ response }) =>
      response(409).json(errorBody("FOLDER_EXISTS", "Folder exists")),
    ),
  );
}

async function createFolder(name: string) {
  const { user } = renderFolders();
  await user.click(screen.getByRole("button", { name: "New folder" }));
  await user.click(screen.getByLabelText("Folder name"));
  if (name) await user.paste(name);
  await user.click(screen.getByRole("button", { name: "Save" }));
  return user;
}

function serveDelete() {
  server.use(
    http.delete("/api/v1/workspaces/{workspace_id}/folders/{folder_id}", ({ response }) =>
      response(204).empty(),
    ),
  );
}

function serveRestore(answer: () => "restored" | "exists" | "conflict") {
  const restored: string[] = [];
  server.use(
    http.post(
      "/api/v1/workspaces/{workspace_id}/folders/{folder_id}/restore",
      ({ params, response }) => {
        restored.push(params.folder_id);
        const outcome = answer();
        if (outcome === "exists") return response(409).json(errorBody("FOLDER_EXISTS", "Conflict"));
        if (outcome === "conflict") {
          return response(409).json(errorBody("FOLDER_RECOVERY_CONFLICT", "Conflict"));
        }
        return response(200).json(PLANNING_FOLDER);
      },
    ),
  );
  return restored;
}

async function deletePlanning() {
  const user = await openPlanningMenu();
  await user.click(screen.getByRole("menuitem", { name: "Delete" }));
  await user.click(screen.getByRole("button", { name: "Delete folder" }));
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
  const bodies = serveCreate();

  // Act
  await createFolder("Research");

  // Assert
  await waitFor(() => expect(bodies).toEqual([{ name: "Research" }]));
});

describe.each([
  ["an empty name", "", "Enter a folder name"],
  ["a blank name", "   ", "Enter a folder name"],
  ["a name over 100 characters", "f".repeat(101), "Use 100 characters or fewer"],
])("%s", (_, name, message) => {
  test("is refused on the field", async () => {
    // Act
    await createFolder(name);

    // Assert
    expect(screen.getByLabelText("Folder name")).toHaveAccessibleDescription(message);
  });

  test("is not sent", async () => {
    // Arrange
    const bodies = serveCreate();

    // Act
    await createFolder(name);

    // Assert
    expect(bodies).toEqual([]);
  });
});

test("a taken name is refused on the field", async () => {
  // Arrange
  refuseCreate();

  // Act
  await createFolder("Planning");

  // Assert
  await waitFor(() =>
    expect(screen.getByLabelText("Folder name")).toHaveAccessibleDescription(
      "A folder with this name already exists",
    ),
  );
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
  await waitFor(() => expect(bodies).toEqual([{ name: "Roadmap" }]));
});

test("a refused create leaves no error in the next dialog", async () => {
  // Arrange
  refuseCreate();
  const user = await createFolder("Planning");
  await waitFor(() =>
    expect(screen.getByLabelText("Folder name")).toHaveAccessibleDescription(
      "A folder with this name already exists",
    ),
  );
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await user.click(screen.getByRole("button", { name: "Manage Planning" }));

  // Act
  await user.click(screen.getByRole("menuitem", { name: "Rename" }));

  // Assert
  expect(screen.getByLabelText("Folder name")).not.toHaveAccessibleDescription();
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

test("a failed folder deletion shows the server's message", async () => {
  // Arrange
  server.use(
    http.delete("/api/v1/workspaces/{workspace_id}/folders/{folder_id}", ({ response }) =>
      response(403).json(errorBody("INSUFFICIENT_ROLE", "Only a Moderator or Owner can do this")),
    ),
  );

  // Act
  await deletePlanning();

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Only a Moderator or Owner can do this",
  );
});

test("Undo restores the deleted folder", async () => {
  // Arrange
  serveDelete();
  const restored = serveRestore(() => "restored");
  const user = await deletePlanning();

  // Act
  await user.click(await screen.findByRole("button", { name: "Undo" }));

  // Assert
  await waitFor(() => expect(restored).toEqual(["planning"]));
});

test("Undo stays after a click elsewhere", async () => {
  // Arrange
  serveDelete();
  const user = await deletePlanning();
  await waitForElementToBeRemoved(() => screen.queryByRole("dialog"));

  // Act
  await user.click(screen.getByRole("button", { name: /All meetings/ }));

  // Assert
  expect(screen.getByRole("button", { name: "Undo" })).toBeVisible();
});

test.for([
  ["exists", /another folder now has its name/i],
  ["conflict", /meetings have changed since deletion/i],
] as const)("a %s restore conflict is explained", async ([outcome, message]) => {
  // Arrange
  serveDelete();
  serveRestore(() => outcome);
  const user = await deletePlanning();

  // Act
  await user.click(await screen.findByRole("button", { name: "Undo" }));

  // Assert
  expect(await screen.findByText(message)).toBeVisible();
});
