import { expect, test } from "vitest";
import { meetingSummary, page } from "@/shared/testing/fixtures";
import { describeFailure, describeMeetingFigures, mapMeeting, matchesStateFilter } from "./model";

const QUEUED = meetingSummary({ processing_state: "queued" });
const FAILED = meetingSummary({ processing_state: "failed" });

test("processing state filter keeps only processing meetings", () => {
  // Arrange
  const meetings = (["recording", "queued", "processing"] as const).map((state) => ({ state }));

  // Act
  const kept = meetings.filter((meeting) => matchesStateFilter(meeting, "processing"));

  // Assert
  expect(kept).toEqual([{ state: "processing" }]);
});

test("a meeting summary carries no recording or failure reason", () => {
  // Act
  const meeting = mapMeeting(meetingSummary());

  // Assert
  expect(meeting).toMatchObject({ recordingAvailable: false, failureReason: null });
});

test("an uploaded meeting is labelled as an upload", () => {
  // Act
  const meeting = mapMeeting(meetingSummary({ source_type: "upload" }));

  // Assert
  expect(meeting.source).toBe("Upload");
});

test("figures of a complete list are exact", () => {
  // Arrange
  const meetings = page([QUEUED, meetingSummary()]);

  // Act
  const figures = describeMeetingFigures(meetings);

  // Assert
  expect(figures).toBe("2 meetings, 1 active");
});

test("a lone meeting is singular", () => {
  // Act
  const figures = describeMeetingFigures(page([meetingSummary()]));

  // Assert
  expect(figures).toBe("1 meeting, 0 active");
});

test("a failed meeting is not active", () => {
  // Act
  const figures = describeMeetingFigures(page([FAILED]));

  // Assert
  expect(figures).toBe("1 meeting, 0 active");
});

test("figures of a truncated list say so for both numbers", () => {
  // Arrange
  const meetings = page([...Array(99).fill(meetingSummary()), QUEUED], "next");

  // Act
  const figures = describeMeetingFigures(meetings);

  // Assert
  expect(figures).toBe("100+ meetings, 1 active in the latest 100");
});

test.for([
  ["transcription_failed", "This recording could not be transcribed."],
  ["notes_failed", "Notes could not be written for this meeting."],
  ["provider_unavailable", "The notes provider was unavailable, so no notes were written."],
  ["provider_rejected", "The notes provider refused the request, so no notes were written."],
  ["processing_timeout", "Processing took too long and was stopped."],
] as const)("%s reads as a sentence", ([reason, text]) => {
  // Act
  const description = describeFailure(reason);

  // Assert
  expect(description).toBe(text);
});

test.for([
  ["an unknown code", "disk_full"],
  ["an inherited property name", "constructor"],
  ["no reason", null],
] as const)("%s reads as the general failure", ([, reason]) => {
  // Act
  const description = describeFailure(reason);

  // Assert
  expect(description).toBe("Processing failed for this meeting.");
});
