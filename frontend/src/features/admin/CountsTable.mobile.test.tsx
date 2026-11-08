import { screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { renderWithProviders } from "@/shared/testing/render";
import { stubViewportWidth } from "@/shared/testing/viewport";
import { CountsTable } from "./CountsTable";

const transcription = {
  job_type: "transcription",
  queued: 2,
  running: 1,
  failed: 0,
  unpublished: 1,
  oldest_queue_wait_seconds: 3603599,
  unknown_queue_waits: 1,
} as const;
const notes = {
  ...transcription,
  job_type: "notes",
  queued: 0,
  oldest_queue_wait_seconds: null,
} as const;

afterEach(() => vi.unstubAllGlobals());

test.for([320, 390, 599])(
  "mobile counts group descriptions with their metrics at %s pixels",
  (width) => {
    // Arrange
    stubViewportWidth(width);
    // Act
    renderWithProviders(<CountsTable counts={[transcription, notes]} />);
    // Assert
    expect(
      within(screen.getByRole("region", { name: "Oldest known queue wait" })).getByText(
        "Longest known wait. Warns above 15 minutes.",
      ),
    ).toBeVisible();
  },
);

test("mobile long waits stay together beside the corresponding job type", () => {
  // Arrange
  stubViewportWidth(320);
  // Act
  renderWithProviders(<CountsTable counts={[transcription, notes]} />);
  // Assert
  expect(
    within(screen.getByRole("region", { name: "Oldest known queue wait" })).getByText(
      "1000h 59m 59s",
    ),
  ).toHaveStyle({ whiteSpace: "nowrap" });
});

test("mobile values retain their transcription and notes labels", () => {
  // Arrange
  stubViewportWidth(390);
  // Act
  renderWithProviders(<CountsTable counts={[transcription, notes]} />);
  // Assert
  expect(
    within(screen.getByRole("region", { name: "Oldest known queue wait" }))
      .getAllByRole("term")
      .map((term) => [term.textContent, term.nextElementSibling?.textContent]),
  ).toEqual([
    ["Transcription", expect.stringContaining("1000h 59m 59s")],
    ["Notes", "None queued"],
  ]);
});

test("mobile unknown waits remain unknown", () => {
  // Arrange
  stubViewportWidth(390);
  // Act
  renderWithProviders(
    <CountsTable counts={[{ ...transcription, oldest_queue_wait_seconds: null }]} />,
  );
  // Assert
  expect(
    within(screen.getByRole("region", { name: "Oldest known queue wait" })).getByRole("definition"),
  ).toHaveTextContent("Unknown");
});
