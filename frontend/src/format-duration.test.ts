import { expect, test } from "vitest";
import { formatDuration } from "./format-duration";

test.each([
  { seconds: 90, expected: "1m 30s" },
  { seconds: 3661, expected: "1h 1m 1s" },
  { seconds: 3605, expected: "1h 5s" },
  { seconds: 3600, expected: "1h" },
])("formats $seconds seconds as $expected", ({ seconds, expected }) => {
  // Act
  const text = formatDuration(seconds);

  // Assert
  expect(text).toBe(expected);
});

test("shows pending when duration is missing", () => {
  // Act
  const text = formatDuration(null);

  // Assert
  expect(text).toBe("Duration pending");
});
