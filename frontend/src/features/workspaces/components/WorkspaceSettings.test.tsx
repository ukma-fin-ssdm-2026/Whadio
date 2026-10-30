import { screen, waitFor } from "@testing-library/react";
import { expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { errorBody, page, workspaceRead } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { WorkspaceSettings } from "./WorkspaceSettings";

function serveWorkspace(changes: Partial<Schemas["WorkspaceRead"]> = {}) {
  const updates: unknown[] = [];
  let workspace = workspaceRead({ name: "Alpha", ...changes });
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}", ({ response }) => response(200).json(workspace)),
    http.patch("/api/v1/workspaces/{workspace_id}", async ({ request, response }) => {
      const body = await request.json();
      updates.push(body);
      workspace = { ...workspace, default_preset: body.default_preset ?? "summary" };
      return response(200).json(workspace);
    }),
    http.get("/api/v1/workspaces", ({ response }) => response(200).json(page([]))),
  );
  return updates;
}

function renderSettings() {
  return renderWithProviders(
    <WorkspaceSettings workspaceId="workspace" assistantSettings={<p>Assistant keys</p>} />,
  );
}

async function choosePreset(label: string) {
  const { user } = renderSettings();
  await user.click(await screen.findByRole("combobox"));
  await user.click(screen.getByRole("option", { name: label }));
}

test("opens on the workspace section", async () => {
  // Arrange
  serveWorkspace();

  // Act
  renderSettings();

  // Assert
  expect(await screen.findByRole("heading", { level: 2 })).toHaveTextContent(
    /^Workspace settings$/,
  );
});

test("describes the workspace it loaded", async () => {
  // Arrange
  serveWorkspace();

  // Act
  renderSettings();

  // Assert
  expect(await screen.findByText(/defaults for Alpha\./)).toBeInTheDocument();
});

test("a loading failure is reported", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "No such workspace")),
    ),
  );

  // Act
  renderSettings();

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("No such workspace");
});

test("choosing AI assistant shows the assistant settings", async () => {
  // Arrange
  serveWorkspace();
  const { user } = renderSettings();

  // Act
  await user.click(screen.getByRole("button", { name: "AI assistant" }));

  // Assert
  expect(screen.getByText("Assistant keys")).toBeInTheDocument();
});

test("choosing AI assistant hides the workspace settings", async () => {
  // Arrange
  serveWorkspace();
  const { user } = renderSettings();
  await screen.findByText("Notes provider");

  // Act
  await user.click(screen.getByRole("button", { name: "AI assistant" }));

  // Assert
  expect(screen.queryByText("Notes provider")).not.toBeInTheDocument();
});

test("marks the chosen section as current", async () => {
  // Arrange
  serveWorkspace();
  const { user } = renderSettings();

  // Act
  await user.click(screen.getByRole("button", { name: "AI assistant" }));

  // Assert
  expect(screen.getByRole("button", { current: true })).toHaveTextContent(/^AI assistant$/);
});

test("an owner's preset choice is saved", async () => {
  // Arrange
  const updates = serveWorkspace();

  // Act
  await choosePreset("Interview");

  // Assert
  await waitFor(() => expect(updates).toEqual([{ default_preset: "interview" }]));
});

test("the saved preset shows as selected", async () => {
  // Arrange
  serveWorkspace();

  // Act
  await choosePreset("Interview");

  // Assert
  await waitFor(() => expect(screen.getByRole("combobox")).toHaveTextContent("Interview"));
});

test("a refused preset change is reported", async () => {
  // Arrange
  serveWorkspace();
  server.use(
    http.patch("/api/v1/workspaces/{workspace_id}", ({ response }) =>
      response(403).json(errorBody("INSUFFICIENT_ROLE", "Owner only")),
    ),
  );

  // Act
  await choosePreset("Detailed");

  // Assert
  expect(await screen.findByText("Owner only")).toBeInTheDocument();
});

test("a member sees the preset without a control", async () => {
  // Arrange
  serveWorkspace({ my_role: "member" });

  // Act
  renderSettings();
  await screen.findByText("Default notes preset");

  // Assert
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
});
