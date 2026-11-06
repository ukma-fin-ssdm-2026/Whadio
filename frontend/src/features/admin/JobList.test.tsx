import { screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { renderWithProviders } from "@/shared/testing/render";
import { stubViewportWidth } from "@/shared/testing/viewport";
import { JobList } from "./JobList";
import { job, STAMP } from "./testing";

afterEach(() => vi.unstubAllGlobals());

test.for([599, 600, 1440])("jobs use the appropriate layout at %s pixels", (width) => {
  // Arrange
  stubViewportWidth(width);
  // Act
  renderWithProviders(<JobList pages={[[job()]]} filters={{}} onWorkspace={() => {}} />);
  // Assert
  expect(screen.getByRole(width < 600 ? "list" : "table")).toBeVisible();
});

test.for([390, 1440])("each fetched page has one observation time at %s pixels", (width) => {
  // Arrange
  stubViewportWidth(width);
  const later = "2026-11-05T11:00:00Z";
  // Act
  renderWithProviders(
    <JobList
      pages={[[job(), job({ job_id: "job-2" })], [job({ job_id: "job-3", as_of: later })]]}
      filters={{}}
      onWorkspace={() => {}}
    />,
  );
  // Assert
  expect(screen.getAllByText(/^Observed /).map((line) => line.textContent)).toEqual([
    `Observed ${new Date(STAMP).toLocaleString()}`,
    `Observed ${new Date(later).toLocaleString()}`,
  ]);
});

test("the desktop row retains failure and timing details", () => {
  // Arrange
  stubViewportWidth(1440);
  // Act
  renderWithProviders(
    <JobList
      pages={[
        [
          job({
            status: "failed",
            attempts_started: 2,
            finished_at: STAMP,
            last_attempt_duration_seconds: 65,
            last_queue_wait_seconds: 10,
            total_elapsed_seconds: 90,
            failure_description: "Timed out.",
          }),
        ],
      ]}
      filters={{}}
      onWorkspace={() => {}}
    />,
  );
  // Assert
  expect(screen.getByRole("button", { name: "Copy job ID job-1" }).closest("tr")).toHaveTextContent(
    /Finished.*Failed.*Last attempt: 1m 5s.*Queue before attempt: 0m 10s.*1m 30s.*2.*Timed out/,
  );
});

test.for([390, 1440])("copying a workspace uses its complete ID at %s pixels", async (width) => {
  // Arrange
  stubViewportWidth(width);
  const id = "29dd39f7-c5c8-438b-9b4f-530839c8fc59";
  const { user } = renderWithProviders(
    <JobList pages={[[job({ workspace_id: id })]]} filters={{}} onWorkspace={() => {}} />,
  );
  // Act
  await user.click(screen.getByRole("button", { name: `Copy workspace ID ${id}` }));
  // Assert
  expect(await navigator.clipboard.readText()).toBe(id);
});

test("the workspace link includes existing filters for opening in another tab", () => {
  // Arrange
  stubViewportWidth(1440);
  // Act
  renderWithProviders(
    <JobList
      pages={[[job()]]}
      filters={{ job_type: "notes", status: "failed" }}
      onWorkspace={() => {}}
    />,
  );
  // Assert
  expect(screen.getByRole("link", { name: "Filter by workspace workspace-alpha" })).toHaveAttribute(
    "href",
    "/admin?job_type=notes&status=failed&workspace_id=workspace-alpha",
  );
});
