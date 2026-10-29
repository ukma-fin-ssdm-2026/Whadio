import { render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { expect, test, vi } from "vitest";
import { MeetingLibrary } from "./MeetingLibrary";

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

const interactive = 'button, a[href], input, select, [role="button"], [tabindex="0"]';

test.for([
  ["recording", "Recording"],
  ["queued", "Queued"],
  ["processing", "Processing"],
] as const)("%s library row is labelled %s", ([state, label]) => {
  // Arrange
  const { container } = renderLibrary(meeting({ state }));

  // Act
  const status = container.querySelector(".MuiChip-label");

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

test("in-progress library row offers no control besides opening the meeting", () => {
  // Arrange
  renderLibrary(meeting({ state: "queued" }));

  // Act
  const controls = screen.getByRole("listitem").querySelectorAll(`:is(${interactive})`);

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

test("failed library row is marked with an error chip", () => {
  // Arrange
  const { container } = renderLibrary(meeting({ state: "failed" }));

  // Act
  const chip = container.querySelector(".MuiChip-root");

  // Assert
  expect(chip).toHaveClass("MuiChip-colorError");
});

test("library without meetings says none were found", () => {
  // Act
  renderLibrary(meeting(), { meetings: [] });

  // Assert
  expect(screen.getByText("No meetings found")).toBeInTheDocument();
});
