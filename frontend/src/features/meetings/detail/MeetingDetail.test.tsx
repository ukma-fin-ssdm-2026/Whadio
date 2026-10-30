import { render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { expect, test } from "vitest";
import { ExportControls } from "@/features/export/components/ExportControls";
import { MeetingDetail } from "./MeetingDetail";

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

function detail(changes: Partial<ComponentProps<typeof MeetingDetail>> = {}) {
  const props = {
    meeting: meeting(),
    tab: "notes",
    transcriptQuery: "",
    onTab: () => {},
    onTranscriptQuery: () => {},
    notes: { content: "Saved notes" },
    transcript: null,
    onRevision: () => {},
    recordingUrl: "",
    loading: false,
    ...changes,
  };
  return (
    <MeetingDetail
      {...props}
      exportControls={
        <ExportControls
          meetingId={props.meeting.id}
          tab={props.tab}
          transcript={props.transcript}
          notes={props.notes}
          loading={props.loading}
        />
      }
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
