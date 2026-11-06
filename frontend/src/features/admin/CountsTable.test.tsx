import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { renderWithProviders } from "@/shared/testing/render";
import { CountsTable } from "./CountsTable";
import { metrics } from "./testing";

const counts = {
  job_type: "transcription",
  queued: 1,
  running: 0,
  failed: 0,
  unpublished: 0,
  oldest_queue_wait_seconds: 0,
  unknown_queue_waits: 0,
} as const;

test("counts compare both job types in columns", () => {
  // Act
  renderWithProviders(<CountsTable counts={[counts, { ...counts, job_type: "notes" }]} />);
  // Assert
  expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
    "Retained jobs",
    "Transcription",
    "Notes",
  ]);
});

test("counts explain publication delays and missing historical waits", () => {
  // Act
  renderWithProviders(<CountsTable counts={metrics.jobs} />);
  // Assert
  expect(screen.getByRole("table")).toHaveTextContent(
    /Queued jobs not yet sent to the broker.*Queued jobs with no recorded queue-entry time/,
  );
});

test.for([
  ["failed", 1, "Failed"],
  ["unpublished", 1, "Not yet published"],
  ["oldest_queue_wait_seconds", 901, "Oldest known queue wait"],
] as const)("%s at %s is highlighted for attention", ([key, value, label]) => {
  // Act
  renderWithProviders(<CountsTable counts={[{ ...counts, [key]: value }]} />);
  // Assert
  expect(screen.getByTitle(`${label} needs attention`).closest("td")).toHaveStyle({
    color: "rgb(237, 108, 2)",
  });
});

test.for([0, 900])("a queue wait of %s seconds has no long-wait warning", (wait) => {
  // Act
  renderWithProviders(<CountsTable counts={[{ ...counts, oldest_queue_wait_seconds: wait }]} />);
  // Assert
  expect(screen.queryByTitle("Oldest known queue wait needs attention")).not.toBeInTheDocument();
});

test("an empty queue does not warn about an inapplicable wait", () => {
  // Act
  renderWithProviders(
    <CountsTable counts={[{ ...counts, queued: 0, oldest_queue_wait_seconds: 999 }]} />,
  );
  // Assert
  expect(screen.queryByTitle("Oldest known queue wait needs attention")).not.toBeInTheDocument();
});

test("zero failed and unpublished counts do not warn", () => {
  // Act
  renderWithProviders(<CountsTable counts={[counts]} />);
  // Assert
  expect(screen.queryAllByTitle(/needs attention/)).toHaveLength(0);
});
