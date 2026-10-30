import { expect, test, vi } from "vitest";
import { notesExportUrl, transcriptExportUrl } from "./export-urls";

test("transcript downloads default to current Markdown with timestamps", () => {
  // Act
  const url = transcriptExportUrl("meeting");

  // Assert
  expect(url).toBe(
    "/api/v1/meetings/meeting/transcript/export?format=markdown&version=current&timestamps=true",
  );
});

test.for(
  (["current", "original"] as const).flatMap((version) =>
    [true, false].map((timestamps) => ({ version, timestamps })),
  ),
)("Markdown download selects $version with timestamps=$timestamps", ({ version, timestamps }) => {
  // Act
  const url = transcriptExportUrl("meeting", { version, timestamps });

  // Assert
  expect(url).toBe(
    `/api/v1/meetings/meeting/transcript/export?format=markdown&version=${version}&timestamps=${timestamps}`,
  );
});

test.for(["current", "original"] as const)(
  "WebVTT download selects %s and retains mandatory timing",
  (version) => {
    // Act
    const url = transcriptExportUrl("meeting", { format: "vtt", version, timestamps: false });

    // Assert
    expect(url).toBe(`/api/v1/meetings/meeting/transcript/export?format=vtt&version=${version}`);
  },
);

test("transcript download encodes the meeting identifier", () => {
  // Act
  const url = transcriptExportUrl("meeting/other?query=yes");

  // Assert
  expect(url.split("/transcript/")[0]).toBe("/api/v1/meetings/meeting%2Fother%3Fquery%3Dyes");
});

test("notes download uses the current notes endpoint and encodes the meeting identifier", () => {
  // Act
  const url = notesExportUrl("meeting/other?query=yes");

  // Assert
  expect(url).toBe("/api/v1/meetings/meeting%2Fother%3Fquery%3Dyes/notes/export");
});

test("downloads from a configured origin with a trailing slash have no double slash", async () => {
  // Arrange
  vi.stubEnv("VITE_API_ORIGIN", "https://example.com/whadio/");
  vi.resetModules();
  const configured = await import("./export-urls");
  vi.unstubAllEnvs();

  // Act
  const url = configured.notesExportUrl("meeting");

  // Assert
  expect(url).toBe("https://example.com/whadio/api/v1/meetings/meeting/notes/export");
});
