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
  return renderWithProviders(<WorkspaceSettings workspaceId="workspace" />);
}

async function choosePreset(label: string) {
  const { user } = renderSettings();
  await user.click(await screen.findByRole("combobox"));
  await user.click(screen.getByRole("option", { name: label }));
}

test("names the settings of the workspace", async () => {
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

test("names the built-in model that writes notes", async () => {
  // Arrange
  serveWorkspace({ notes_provider: "whadio", notes_model: "gemma4:12b-it-qat" });

  // Act
  renderSettings();

  // Assert
  expect(
    await screen.findByText("Whadio gemma4:12b-it-qat is used for generated notes."),
  ).toBeInTheDocument();
});

test("names the external model that writes notes", async () => {
  // Arrange
  serveWorkspace({ notes_provider: "anthropic", notes_model: "claude-sonnet-5-5" });

  // Act
  renderSettings();

  // Assert
  expect(
    await screen.findByText(/^Anthropic claude-sonnet-5-5 is used for generated notes\./),
  ).toBeInTheDocument();
});

test("states that transcripts go to an external provider", async () => {
  // Arrange
  serveWorkspace({ notes_provider: "anthropic", notes_model: "claude-sonnet-5-5" });

  // Act
  renderSettings();

  // Assert
  expect(
    await screen.findByText(/Transcripts in the context set are sent to Anthropic\.$/),
  ).toBeInTheDocument();
});

test("a member is told that transcripts go to an external provider", async () => {
  // Arrange
  serveWorkspace({
    my_role: "member",
    notes_provider: "anthropic",
    notes_model: "claude-sonnet-5-5",
  });

  // Act
  renderSettings();

  // Assert
  expect(
    await screen.findByText(/Transcripts in the context set are sent to Anthropic\.$/),
  ).toBeInTheDocument();
});

test("says nothing about sending transcripts for the built-in model", async () => {
  // Arrange
  serveWorkspace({ notes_provider: "whadio" });

  // Act
  renderSettings();
  await screen.findByText(/is used for generated notes\./);

  // Assert
  expect(screen.queryByText(/Transcripts in the context set/)).not.toBeInTheDocument();
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

test("settings have no workspace access switch", async () => {
  // Arrange
  serveWorkspace();

  // Act
  renderSettings();
  await screen.findByRole("heading", { level: 2 });

  // Assert
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
});
