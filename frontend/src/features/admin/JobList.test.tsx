import { fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { renderWithProviders } from "@/shared/testing/render";
import { stubViewportWidth } from "@/shared/testing/viewport";
import { JobList } from "./JobList";
import { job, STAMP } from "./testing";

afterEach(() => vi.unstubAllGlobals());

test.for([599, 600, 768, 1024, 1199, 1200, 1280, 1440])(
  "jobs use the appropriate layout at %s pixels",
  (width) => {
    // Arrange
    stubViewportWidth(width);
    // Act
    renderWithProviders(
      <JobList pages={[[job()]]} workspaceHref={() => "#"} onWorkspace={() => {}} />,
    );
    // Assert
    expect(screen.getByRole(width < 1200 ? "list" : "table")).toBeVisible();
  },
);

test.for([390, 1440])("each fetched page has one observation time at %s pixels", (width) => {
  // Arrange
  stubViewportWidth(width);
  const later = "2026-11-05T11:00:00Z";
  // Act
  renderWithProviders(
    <JobList
      pages={[[job(), job({ job_id: "job-2" })], [job({ job_id: "job-3", as_of: later })]]}
      workspaceHref={() => "#"}
      onWorkspace={() => {}}
    />,
  );
  // Assert
  expect(
    screen
      .getAllByText(/^Jobs observed /)
      .map((line) => ({ text: line.textContent, outsideTable: line.closest("table") === null })),
  ).toEqual([
    { text: `Jobs observed ${new Date(STAMP).toLocaleString()}`, outsideTable: true },
    { text: `Jobs observed ${new Date(later).toLocaleString()}`, outsideTable: true },
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
      workspaceHref={() => "#"}
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
    <JobList
      pages={[[job({ workspace_id: id })]]}
      workspaceHref={() => "#"}
      onWorkspace={() => {}}
    />,
  );
  // Act
  await user.click(screen.getByRole("button", { name: `Copy workspace ID ${id}` }));
  // Assert
  expect(await navigator.clipboard.readText()).toBe(id);
});

test("the workspace link uses the address supplied by the route", () => {
  // Arrange
  stubViewportWidth(1440);
  // Act
  renderWithProviders(
    <JobList
      pages={[[job()]]}
      workspaceHref={(id) => `/whadio/admin?job_type=notes&status=failed&workspace_id=${id}`}
      onWorkspace={() => {}}
    />,
  );
  // Assert
  expect(screen.getByRole("link", { name: "Filter by workspace workspace-alpha" })).toHaveAttribute(
    "href",
    "/whadio/admin?job_type=notes&status=failed&workspace_id=workspace-alpha",
  );
});

test("a plain workspace click filters in place and prevents browser navigation", () => {
  // Arrange
  const onWorkspace = vi.fn();
  renderWithProviders(
    <JobList pages={[[job()]]} workspaceHref={() => "#"} onWorkspace={onWorkspace} />,
  );
  // Act
  const defaultAllowed = fireEvent.click(
    screen.getByRole("link", { name: "Filter by workspace workspace-alpha" }),
  );
  // Assert
  expect({ defaultAllowed, calls: onWorkspace.mock.calls }).toEqual({
    defaultAllowed: false,
    calls: [["workspace-alpha"]],
  });
});

test.for(["ctrlKey", "metaKey", "shiftKey", "altKey"])(
  "a workspace click with %s preserves browser navigation",
  (modifier) => {
    // Arrange
    const onWorkspace = vi.fn();
    renderWithProviders(
      <JobList pages={[[job()]]} workspaceHref={() => "#"} onWorkspace={onWorkspace} />,
    );
    // Act
    const defaultAllowed = fireEvent.click(
      screen.getByRole("link", { name: "Filter by workspace workspace-alpha" }),
      { [modifier]: true },
    );
    // Assert
    expect({ defaultAllowed, calls: onWorkspace.mock.calls }).toEqual({
      defaultAllowed: true,
      calls: [],
    });
  },
);

test.for([390, 1440])(
  "a queued retry hides the previous attempt's queue wait at %s pixels",
  (width) => {
    // Arrange
    stubViewportWidth(width);
    // Act
    renderWithProviders(
      <JobList
        pages={[[job({ attempts_started: 1, last_queue_wait_seconds: 12 })]]}
        workspaceHref={() => "#"}
        onWorkspace={() => {}}
      />,
    );
    // Assert
    expect(screen.queryByText(/Queue before attempt/)).not.toBeInTheDocument();
  },
);

test.for([390, 1440])("an adjusted job explains clock skew at %s pixels", (width) => {
  // Arrange
  stubViewportWidth(width);
  // Act
  renderWithProviders(
    <JobList
      pages={[[job({ timing_anomaly: true })]]}
      workspaceHref={() => "#"}
      onWorkspace={() => {}}
    />,
  );
  // Assert
  expect(screen.getByText("Timing adjusted for clock skew.")).toBeVisible();
});
