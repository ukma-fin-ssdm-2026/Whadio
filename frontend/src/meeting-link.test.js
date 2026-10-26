import assert from "node:assert/strict";
import test from "node:test";
import { meetingLibraryPath, meetingPath, readMeetingLink } from "./meeting-link.js";

test("an original transcript link keeps its requested revision", () => {
  assert.deepEqual(readMeetingLink("https://example.com/meetings/meeting?revision_id=original"), {
    meetingId: "meeting",
    revisionId: "original",
  });
});

test("a regular meeting link selects the current version", () => {
  assert.deepEqual(readMeetingLink("https://example.com/meetings/meeting"), {
    meetingId: "meeting",
    revisionId: null,
  });
});

test("a deployment prefix survives meeting and revision navigation", () => {
  assert.equal(
    meetingPath("https://example.com/whadio/meetings/old?revision_id=old", "new", "original"),
    "/whadio/meetings/new?revision_id=original",
  );
});

test("leaving a deep link clears the revision and preserves the deployment prefix", () => {
  const path = meetingLibraryPath(
    "https://example.com/whadio/meetings/meeting?revision_id=original",
  );
  assert.equal(path, "/whadio/meetings/");
  assert.equal(readMeetingLink(`https://example.com${path}`), null);
});

test("a version selector is URL encoded", () => {
  assert.equal(
    meetingPath("https://example.com/", "meeting", "bad&other=value"),
    "/meetings/meeting?revision_id=bad%26other%3Dvalue",
  );
});

test("back navigation can restore a previous revision", () => {
  const href = "https://example.com/whadio/meetings/meeting?revision_id=original";
  const current = meetingPath(href, "meeting");
  assert.equal(readMeetingLink(`https://example.com${current}`).revisionId, null);
  assert.equal(readMeetingLink(href).revisionId, "original");
});
