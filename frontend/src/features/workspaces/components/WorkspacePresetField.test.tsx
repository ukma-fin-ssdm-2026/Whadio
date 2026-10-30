import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { workspaceRead } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { WorkspacePresetField } from "./WorkspacePresetField";

test("shows the workspace's default preset", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}", ({ response }) =>
      response(200).json(workspaceRead({ default_preset: "interview" })),
    ),
  );

  // Act
  renderWithProviders(<WorkspacePresetField workspaceId="workspace" />);

  // Assert
  expect(await screen.findByText("Interview (workspace default)")).toBeInTheDocument();
});
