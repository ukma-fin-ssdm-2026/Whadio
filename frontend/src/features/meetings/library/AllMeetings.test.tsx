import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { errorBody, meetingSummary, page } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { AllMeetings } from "./AllMeetings";

const ALPHA = meetingSummary({
  id: "alpha-meeting",
  name: "Alpha retro",
  workspace_id: "alpha",
  recorded_at: "2026-10-20T10:00:00Z",
});
const BETA = meetingSummary({
  id: "beta-meeting",
  name: "Beta planning",
  workspace_id: "beta",
  recorded_at: "2026-10-25T10:00:00Z",
});

function serveWorkspaces(nextCursor: string | null = null) {
  const requests: string[] = [];
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/meetings", ({ params, request, response }) => {
      requests.push(params.workspace_id + new URL(request.url).search);
      const meeting = params.workspace_id === "alpha" ? ALPHA : BETA;
      return response(200).json(page([meeting], nextCursor));
    }),
  );
  return requests;
}

function renderAll() {
  return renderWithProviders(
    <AllMeetings workspaceIds={["alpha", "beta"]} selectedMeetingId="" onMeeting={() => {}} />,
  );
}

test("merges the workspaces with the newest recording first", async () => {
  // Arrange
  serveWorkspaces();

  // Act
  renderAll();
  await screen.findByText("Alpha retro");

  // Assert
  expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("Beta planning");
});

test("reads one page per workspace", async () => {
  // Arrange
  const requests = serveWorkspaces();

  // Act
  renderAll();
  await screen.findByText("Alpha retro");

  // Assert
  expect(requests.toSorted()).toEqual(["alpha?limit=100", "beta?limit=100"]);
});

test("the name filter reaches every workspace", async () => {
  // Arrange
  const requests = serveWorkspaces();
  const { user } = renderAll();
  await screen.findByText("Alpha retro");
  requests.length = 0;

  // Act
  await user.type(screen.getByPlaceholderText("Filter by name"), "retro");
  await screen.findByText("Alpha retro");
  await expect.poll(() => requests.length).toBe(2);

  // Assert
  expect(requests.toSorted()).toEqual(["alpha?limit=100&name=retro", "beta?limit=100&name=retro"]);
});

test("a workspace with more meetings is pointed at", async () => {
  // Arrange
  serveWorkspaces("next");

  // Act
  renderAll();

  // Assert
  expect(await screen.findByText(/Open a workspace to see the rest/)).toBeInTheDocument();
});

test("complete workspaces are not pointed at", async () => {
  // Arrange
  serveWorkspaces();

  // Act
  renderAll();
  await screen.findByText("Alpha retro");

  // Assert
  expect(screen.queryByText(/Open a workspace to see the rest/)).not.toBeInTheDocument();
});

test("a workspace that fails is reported beside the others", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/meetings", ({ params, response }) =>
      params.workspace_id === "alpha"
        ? response(404).json(errorBody("NOT_FOUND", "No such workspace"))
        : response(200).json(page([BETA])),
    ),
  );

  // Act
  renderAll();

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("No such workspace");
});

test("no workspaces at all reads as no meetings", async () => {
  // Arrange
  serveWorkspaces();

  // Act
  renderWithProviders(<AllMeetings workspaceIds={[]} selectedMeetingId="" onMeeting={() => {}} />);

  // Assert
  expect(await screen.findByText("No meetings yet")).toBeInTheDocument();
});
