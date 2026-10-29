import { expect, test } from "vitest";
import { api } from "./api";

test("transcript downloads default to current Markdown with timestamps", () => {
  // Act
  const url = api.transcriptExportUrl("meeting");

  // Assert
  expect(url).toBe(
    "/api/v1/meetings/meeting/transcript/export?format=markdown&version=current&timestamps=true",
  );
});

test.for(
  ["current", "original"].flatMap((version) =>
    [true, false].map((timestamps) => ({ version, timestamps })),
  ),
)("Markdown download selects $version with timestamps=$timestamps", ({ version, timestamps }) => {
  // Act
  const url = api.transcriptExportUrl("meeting", { version, timestamps });

  // Assert
  expect(url).toBe(
    `/api/v1/meetings/meeting/transcript/export?format=markdown&version=${version}&timestamps=${timestamps}`,
  );
});

test.for(["current", "original"])(
  "WebVTT download selects %s and retains mandatory timing",
  (version) => {
    // Act
    const url = api.transcriptExportUrl("meeting", { format: "vtt", version, timestamps: false });

    // Assert
    expect(url).toBe(`/api/v1/meetings/meeting/transcript/export?format=vtt&version=${version}`);
  },
);

test("transcript download encodes the meeting identifier", () => {
  // Act
  const url = api.transcriptExportUrl("meeting/other?query=yes");

  // Assert
  expect(url.split("/transcript/")[0]).toBe("/api/v1/meetings/meeting%2Fother%3Fquery%3Dyes");
});

test("notes download uses the current notes endpoint and encodes the meeting identifier", () => {
  // Act
  const url = api.notesExportUrl("meeting/other?query=yes");

  // Assert
  expect(url).toBe("/api/v1/meetings/meeting%2Fother%3Fquery%3Dyes/notes/export");
});
