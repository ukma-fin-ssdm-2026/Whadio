import assert from "node:assert/strict";
import test from "node:test";

import { formatDuration } from "./format-duration.js";

test("formats a duration shorter than one hour", () => {
  assert.equal(formatDuration(90), "1m 30s");
});

test("shows pending when duration is missing", () => {
  assert.equal(formatDuration(null), "Duration pending");
});

test("formats a duration longer than one hour", () => {
  assert.equal(formatDuration(3661), "1h 1m 1s");
});

test("omits zero minutes from an hour duration", () => {
  assert.equal(formatDuration(3605), "1h 5s");
});