import { render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { expect, test, vi } from "vitest";
import { MeetingDetail, MeetingLibrary, matchesStateFilter } from "./App";

function meeting(changes: Record<string, string> = {}) {
  return {
    id: "meeting",
    workspaceId: "workspace",
    title: "Weekly sync",
    date: "2026-10-25T10:00:00Z",
    state: "processed",
    duration: "5s",
    source: "Google Meet",
    recordingAvailable: false,
    failureReason: null,
    ...changes,
  };
}

function transcript(revisionId: string) {
  return {
    revision: { id: revisionId, revision_type: revisionId === "original" ? "original" : "edited" },
    original_revision_id: "original",
    is_edited: true,
    speakers: [],
    segments: [],
  };
}

function renderLibrary(
  item: ReturnType<typeof meeting>,
  changes: Partial<ComponentProps<typeof MeetingLibrary>> = {},
) {
  return render(
    <MeetingLibrary
      title="Workspace library"
      meetings={[item]}
      query=""
      stateFilter="all"
      onQuery={() => {}}
      onStateFilter={() => {}}
      onMeeting={() => {}}
      selectedMeetingId=""
      {...changes}
    />,
  );
}

async function openStateFilter(changes: Partial<ComponentProps<typeof MeetingLibrary>> = {}) {
  renderLibrary(meeting(), changes);
  await userEvent.click(screen.getByRole("combobox"));
  return screen.getAllByRole("option");
}

function detail(changes: Partial<ComponentProps<typeof MeetingDetail>> = {}) {
  return (
    <MeetingDetail
      meeting={meeting()}
      tab="notes"
      transcriptQuery=""
      onTab={() => {}}
      onTranscriptQuery={() => {}}
      notes={{ content: "Saved notes" }}
      transcript={null}
      onRevision={() => {}}
      recordingUrl=""
      loading={false}
      {...changes}
    />
  );
}

function renderDetail(changes: Partial<ComponentProps<typeof MeetingDetail>> = {}) {
  return render(detail(changes));
}

async function openTranscriptDownloads() {
  const view = renderDetail({ tab: "transcript", transcript: transcript("edited") });
  await userEvent.click(screen.getByRole("button", { name: "Download transcript" }));
  return view;
}

const interactive = 'button, a[href], input, select, [role="button"], [tabindex="0"]';

test.for([
  ["recording", "Recording"],
  ["queued", "Queued"],
  ["processing", "Processing"],
] as const)("%s library row is labelled %s", ([state, label]) => {
  // Arrange
  const { container } = renderLibrary(meeting({ state }));

  // Act
  const status = container.querySelector(".processing-status");

  // Assert
  expect(status).toHaveTextContent(new RegExp(`^${label}$`));
});

test("state filter offers each in-progress state under its row label", async () => {
  // Arrange
  const options = await openStateFilter();

  // Act
  const labels = options.map((option) => option.textContent);

  // Assert
  expect(labels).toEqual([
    "All states",
    "Recording",
    "Queued",
    "Processing",
    "Processed",
    "Failed",
  ]);
});

test("choosing Processing in the state filter selects the processing state", async () => {
  // Arrange
  const onStateFilter = vi.fn();
  await openStateFilter({ onStateFilter });

  // Act
  await userEvent.click(screen.getByRole("option", { name: "Processing" }));

  // Assert
  expect(onStateFilter).toHaveBeenCalledExactlyOnceWith("processing");
});

test("processing state filter keeps only processing meetings", () => {
  // Arrange
  const meetings = ["recording", "queued", "processing"].map((state) => meeting({ state }));

  // Act
  const kept = meetings.filter((item) => matchesStateFilter(item, "processing"));

  // Assert
  expect(kept.map((item) => item.state)).toEqual(["processing"]);
});

test("in-progress library row offers no control besides opening the meeting", () => {
  // Arrange
  const { container } = renderLibrary(meeting({ state: "queued" }));

  // Act
  const controls = container.querySelectorAll(`.meeting-row :is(${interactive})`);

  // Assert
  expect(controls).toHaveLength(1);
});

test("in-progress library row shows a progress indicator", () => {
  // Act
  renderLibrary(meeting({ state: "queued" }));

  // Assert
  expect(screen.getByRole("progressbar")).toBeInTheDocument();
});

test("processed library row shows no progress indicator", () => {
  // Act
  renderLibrary(meeting());

  // Assert
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
});

test("meeting header has no workspace access control", () => {
  // Act
  renderDetail();

  // Assert
  expect(screen.queryByLabelText("Workspace access")).not.toBeInTheDocument();
});

test("meeting header names the source as text beside the date", () => {
  // Arrange
  const { container } = renderDetail();

  // Act
  const meta = container.querySelector(".meeting-date");

  // Assert
  expect(meta).toHaveTextContent(/ · Google Meet$/);
});

test("queued meeting notes panel is headed Queued", () => {
  // Arrange
  const { container } = renderDetail({ meeting: meeting({ state: "queued" }), notes: null });

  // Act
  const heading = container.querySelector(".processing-panel p");

  // Assert
  expect(heading).toHaveTextContent(/^Queued$/);
});

test("in-progress notes panel offers no control", () => {
  // Arrange
  const { container } = renderDetail({ meeting: meeting({ state: "queued" }), notes: null });

  // Act
  const controls = container.querySelectorAll(`.processing-panel :is(${interactive})`);

  // Assert
  expect(controls).toHaveLength(0);
});

test("transcript download menu closes when another revision is shown", async () => {
  // Arrange
  const { rerender } = await openTranscriptDownloads();

  // Act
  rerender(detail({ tab: "transcript", transcript: transcript("original") }));

  // Assert
  expect(screen.getByRole("button", { name: "Download transcript" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});

test("transcript download menu stays open when the same revision reloads", async () => {
  // Arrange
  const { rerender } = await openTranscriptDownloads();

  // Act
  rerender(detail({ tab: "transcript", transcript: transcript("edited") }));

  // Assert
  expect(screen.getByRole("button", { name: "Download transcript" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
});
