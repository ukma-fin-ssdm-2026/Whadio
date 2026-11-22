import { expect, test } from "vitest";
import { recordedRange } from "./dateRange";

test("one day as both ends spans that day", () => {
  // Act
  const range = recordedRange("2026-10-05", "2026-10-05");

  // Assert
  expect(range).toEqual({
    recordedFrom: new Date(2026, 9, 5).toISOString(),
    recordedTo: new Date(2026, 9, 6).toISOString(),
  });
});

test("an end before the start is unordered", () => {
  // Act
  const range = recordedRange("2026-10-05", "2026-10-04");

  // Assert
  expect(range).toBe("unordered");
});
