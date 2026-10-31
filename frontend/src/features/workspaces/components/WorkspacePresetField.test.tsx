import { screen, waitFor } from "@testing-library/react";
import { expect, test } from "vitest";
import { errorBody, workspaceRead } from "@/shared/testing/fixtures";
import { createTestQueryClient, renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { workspaceQueries } from "../api/workspaces";
import { WorkspacePresetField } from "./WorkspacePresetField";

function serveWorkspace() {
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}", ({ response }) =>
      response(200).json(workspaceRead({ default_preset: "interview" })),
    ),
  );
}

function failWorkspace() {
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "No such workspace")),
    ),
  );
}

test("shows the workspace's default preset", async () => {
  // Arrange
  serveWorkspace();

  // Act
  renderWithProviders(<WorkspacePresetField workspaceId="workspace" />);

  // Assert
  expect(await screen.findByText("Interview (workspace default)")).toBeInTheDocument();
});

test("shows progress while the preset loads", () => {
  // Arrange
  serveWorkspace();

  // Act
  renderWithProviders(<WorkspacePresetField workspaceId="workspace" />);

  // Assert
  expect(screen.getByRole("progressbar", { name: "Loading note preset" })).toBeInTheDocument();
});

test("a failed load shows the API's message", async () => {
  // Arrange
  failWorkspace();

  // Act
  renderWithProviders(<WorkspacePresetField workspaceId="workspace" />);

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("No such workspace");
});

test("a failed load says uploads still use the workspace default", async () => {
  // Arrange
  failWorkspace();

  // Act
  renderWithProviders(<WorkspacePresetField workspaceId="workspace" />);

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Uploads still use the workspace default.",
  );
});

test("a failed refresh keeps showing the known preset", async () => {
  // Arrange
  failWorkspace();
  const queryClient = createTestQueryClient();
  const { queryKey } = workspaceQueries.detail("workspace");
  queryClient.setQueryData(queryKey, workspaceRead({ default_preset: "detailed" }));

  // Act
  renderWithProviders(<WorkspacePresetField workspaceId="workspace" />, queryClient);
  await waitFor(() => expect(queryClient.getQueryState(queryKey)?.status).toBe("error"));

  // Assert
  expect(screen.getByText("Detailed (workspace default)")).toBeInTheDocument();
});
