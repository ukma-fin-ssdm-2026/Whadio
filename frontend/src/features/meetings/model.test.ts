import { expect, test } from "vitest";
import { matchesStateFilter } from "./model";

test("processing state filter keeps only processing meetings", () => {
  // Arrange
  const meetings = ["recording", "queued", "processing"].map((state) => ({ state }));

  // Act
  const kept = meetings.filter((meeting) => matchesStateFilter(meeting, "processing"));

  // Assert
  expect(kept).toEqual([{ state: "processing" }]);
});
