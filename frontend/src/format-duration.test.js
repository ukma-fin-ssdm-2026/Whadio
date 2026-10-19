import assert from "node:assert/strict";
import test from "node:test";

import { formatDuration } from "./format-duration.js";

const durationCases = [
  { seconds: 90, expected: "1m 30s" },
  { seconds: 3661, expected: "1h 1m 1s" },
  { seconds: 3605, expected: "1h 5s" },
  { seconds: 3600, expected: "1h" },
];

for (const { seconds, expected } of durationCases) {
  test(`formats ${seconds} seconds as ${expected}`, () => {
    assert.equal(formatDuration(seconds), expected);
  });
}

test("shows pending when duration is missing", () => {
  assert.equal(formatDuration(null), "Duration pending");
});
