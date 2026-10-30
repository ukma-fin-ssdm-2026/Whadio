import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { errorBody, meetingSummary, page } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { MeetingFigures } from "./MeetingFigures";

function renderFigures() {
  renderWithProviders(<MeetingFigures workspaceId="workspace" />);
}

test("reports a truncated list as 100+", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/meetings", ({ response }) =>
      response(200).json(page(Array(100).fill(meetingSummary()), "next")),
    ),
  );

  // Act
  renderFigures();

  // Assert
  expect(await screen.findByText(/^100\+ meetings/)).toBeInTheDocument();
});

test("says so while loading", () => {
  // Arrange
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/meetings", ({ response }) =>
      response(200).json(page([])),
    ),
  );

  // Act
  renderFigures();

  // Assert
  expect(screen.getByText("Loading meetings")).toBeInTheDocument();
});

test("says so when the meetings cannot be read", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/meetings", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "No such workspace")),
    ),
  );

  // Act
  renderFigures();

  // Assert
  expect(await screen.findByText("Meetings unavailable")).toBeInTheDocument();
});
