import { screen } from "@testing-library/react";
import { useState } from "react";
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

function Library({
  workspaceIds,
  initialRange = { from: "", to: "" },
}: {
  workspaceIds: string[];
  initialRange?: { from: string; to: string };
}) {
  const [name, setName] = useState("");
  const [from, setFrom] = useState(initialRange.from);
  const [to, setTo] = useState(initialRange.to);
  return (
    <AllMeetings
      workspaceIds={workspaceIds}
      selectedMeetingId=""
      onMeeting={() => {}}
      name={name}
      stateFilter="all"
      from={from}
      to={to}
      onName={setName}
      onStateFilter={() => {}}
      onFrom={setFrom}
      onTo={setTo}
      onClear={() => {
        setName("");
        setFrom("");
        setTo("");
      }}
    />
  );
}

function renderAll(initialRange?: { from: string; to: string }) {
  return renderWithProviders(
    <Library workspaceIds={["alpha", "beta"]} initialRange={initialRange} />,
  );
}

const recorded = (range: Record<string, Date>) =>
  new URLSearchParams({
    limit: "100",
    ...Object.fromEntries(Object.entries(range).map(([key, day]) => [key, day.toISOString()])),
  });

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

test("the date range reaches every workspace in local time with the end day included", async () => {
  // Arrange
  const requests = serveWorkspaces();
  const { user } = renderAll();
  await screen.findByText("Alpha retro");
  requests.length = 0;

  // Act
  await user.type(screen.getByLabelText("From"), "2026-10-05");
  await user.type(screen.getByLabelText("To"), "2026-10-31");
  await expect.poll(() => requests.length).toBeGreaterThanOrEqual(2);

  // Assert
  const search = recorded({
    recorded_from: new Date(2026, 9, 5),
    recorded_to: new Date(2026, 10, 1),
  });
  expect(requests.slice(-2).toSorted()).toEqual([`alpha?${search}`, `beta?${search}`]);
});

test.for([
  ["From", { recorded_from: new Date(2026, 9, 5) }],
  ["To", { recorded_to: new Date(2026, 9, 6) }],
] as const)("only the %s date narrows the list to that bound", async ([label, bound]) => {
  // Arrange
  const requests = serveWorkspaces();
  const { user } = renderAll();
  await screen.findByText("Alpha retro");
  requests.length = 0;

  // Act
  await user.type(screen.getByLabelText(label), "2026-10-05");
  await expect.poll(() => requests.length).toBe(2);

  // Assert
  expect(requests.toSorted()).toEqual([`alpha?${recorded(bound)}`, `beta?${recorded(bound)}`]);
});

test("an end before the start is refused and nothing is requested", async () => {
  // Arrange
  const requests = serveWorkspaces();

  // Act
  renderAll({ from: "2026-10-05", to: "2026-10-04" });

  // Assert
  expect(await screen.findByText("End date is before the start date")).toBeInTheDocument();
  expect(requests).toEqual([]);
});

test("a range that matches nothing says so and clearing the filters brings the list back", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/meetings", ({ request, response }) =>
      response(200).json(
        page(new URL(request.url).searchParams.has("recorded_from") ? [] : [ALPHA]),
      ),
    ),
  );
  const { user } = renderAll({ from: "2026-01-01", to: "" });
  await screen.findByText("No meetings match these filters");

  // Act
  await user.click(screen.getByRole("button", { name: "Clear filters" }));

  // Assert
  expect(await screen.findAllByText("Alpha retro")).toHaveLength(2);
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
  renderWithProviders(<Library workspaceIds={[]} />);

  // Assert
  expect(await screen.findByText("No meetings yet")).toBeInTheDocument();
});
