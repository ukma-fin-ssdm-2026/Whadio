import { render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { expect, test, vi } from "vitest";
import { transcriptRead } from "@/shared/testing/fixtures";
import { TranscriptPanel } from "./TranscriptPanel";

const EDITED = transcriptRead({
  is_edited: true,
  original_revision_id: "original",
  revision: { ...transcriptRead().revision, id: "edited", revision_type: "edited" },
  speakers: [{ id: "speaker", display_name: "Olena Bondar", is_unnamed: false }],
  segments: [
    { id: "one", speaker_id: "speaker", start_seconds: 65, end_seconds: 70, text: "Budget agreed" },
    { id: "two", speaker_id: null, start_seconds: 75, end_seconds: 80, text: "Next steps" },
  ],
});

function renderPanel(changes: Partial<ComponentProps<typeof TranscriptPanel>> = {}) {
  return render(
    <TranscriptPanel
      transcript={EDITED}
      missing={false}
      loading={false}
      failed={false}
      query=""
      onQuery={() => {}}
      onRevision={() => {}}
      {...changes}
    />,
  );
}

test("segments show their speaker and start time", () => {
  // Act
  renderPanel();

  // Assert
  expect(screen.getByText("Olena Bondar").parentElement).toHaveTextContent("01:05");
});

test("a segment without a speaker is labelled unknown", () => {
  // Act
  renderPanel();

  // Assert
  expect(screen.getByText("Unknown speaker")).toBeInTheDocument();
});

test("search matches the segment text", () => {
  // Act
  renderPanel({ query: "BUDGET" });

  // Assert
  expect(screen.queryByText("Next steps")).not.toBeInTheDocument();
});

test("search matches the speaker", () => {
  // Act
  renderPanel({ query: "olena" });

  // Assert
  expect(screen.getByText("Budget agreed")).toBeInTheDocument();
});

test("a search with no match says so", () => {
  // Act
  renderPanel({ query: "absent" });

  // Assert
  expect(screen.getByText("No transcript matches your search.")).toBeInTheDocument();
});

test("typing searches", async () => {
  // Arrange
  const onQuery = vi.fn();
  renderPanel({ onQuery });

  // Act
  await userEvent.type(screen.getByPlaceholderText("Search transcript"), "a");

  // Assert
  expect(onQuery).toHaveBeenCalledWith("a");
});

test("an edited transcript links to its original", async () => {
  // Arrange
  const onRevision = vi.fn();
  renderPanel({ onRevision });

  // Act
  await userEvent.click(screen.getByRole("button", { name: "View original transcript" }));

  // Assert
  expect(onRevision).toHaveBeenCalledWith("original");
});

test("an unedited transcript offers no other revision", () => {
  // Act
  renderPanel({ transcript: transcriptRead() });

  // Assert
  expect(screen.queryByRole("button", { name: /transcript$/ })).not.toBeInTheDocument();
});

test("a missing transcript waits for its query before saying so", () => {
  // Act
  renderPanel({ transcript: null, loading: true });

  // Assert
  expect(screen.queryByText("Transcript is not available yet.")).not.toBeInTheDocument();
});

test("a meeting without a transcript says so", () => {
  // Act
  renderPanel({ transcript: null });

  // Assert
  expect(screen.getByText("Transcript is not available yet.")).toBeInTheDocument();
});

test("no transcript yet says so", () => {
  // Act
  renderPanel({ transcript: null });

  // Assert
  expect(screen.getByText("Transcript is not available yet.")).toBeInTheDocument();
});

test("a transcript that will never come says so", () => {
  // Act
  renderPanel({ transcript: null, missing: true });

  // Assert
  expect(screen.getByText("This meeting has no transcript.")).toBeInTheDocument();
});

test("a failed request claims nothing about a transcript that was never read", () => {
  // Act
  renderPanel({ transcript: null, missing: true, failed: true });

  // Assert
  expect(screen.queryByText("This meeting has no transcript.")).not.toBeInTheDocument();
});

test("a failed refresh leaves the search over the shown transcript working", () => {
  // Act
  renderPanel({ query: "absent", failed: true });

  // Assert
  expect(screen.getByText("No transcript matches your search.")).toBeInTheDocument();
});
