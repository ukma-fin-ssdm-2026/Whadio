import { expect, test } from "vitest";
import { meetingLibraryPath, meetingPath, readMeetingLink } from "./meeting-link";

test("an original transcript link keeps its requested revision", () => {
  // Act
  const link = readMeetingLink("https://example.com/meetings/meeting?revision_id=original");

  // Assert
  expect(link).toEqual({ meetingId: "meeting", revisionId: "original" });
});

test("a regular meeting link selects the current version", () => {
  // Act
  const link = readMeetingLink("https://example.com/meetings/meeting");

  // Assert
  expect(link).toEqual({ meetingId: "meeting", revisionId: null });
});

test("a deployment prefix survives meeting and revision navigation", () => {
  // Act
  const path = meetingPath(
    "https://example.com/whadio/meetings/old?revision_id=old",
    "new",
    "original",
  );

  // Assert
  expect(path).toBe("/whadio/meetings/new?revision_id=original");
});

test("leaving a deep link clears the revision and preserves the deployment prefix", () => {
  // Act
  const path = meetingLibraryPath(
    "https://example.com/whadio/meetings/meeting?revision_id=original",
  );

  // Assert
  expect(path).toBe("/whadio/meetings/");
});

test("the library path is not a meeting link", () => {
  // Arrange
  const path = meetingLibraryPath(
    "https://example.com/whadio/meetings/meeting?revision_id=original",
  );

  // Act
  const link = readMeetingLink(`https://example.com${path}`);

  // Assert
  expect(link).toBeNull();
});

test("a version selector is URL encoded", () => {
  // Act
  const path = meetingPath("https://example.com/", "meeting", "bad&other=value");

  // Assert
  expect(path).toBe("/meetings/meeting?revision_id=bad%26other%3Dvalue");
});

test("back navigation can restore a previous revision", () => {
  // Arrange
  const href = "https://example.com/whadio/meetings/meeting?revision_id=original";
  const current = meetingPath(href, "meeting");

  // Act
  const revisions = [readMeetingLink(`https://example.com${current}`), readMeetingLink(href)].map(
    (link) => link?.revisionId,
  );

  // Assert
  expect(revisions).toEqual([null, "original"]);
});
