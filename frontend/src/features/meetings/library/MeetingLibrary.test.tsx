import { fireEvent, render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { expect, test, vi } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { meetingRead } from "@/shared/testing/fixtures";
import { mapMeeting } from "../model";
import { MeetingLibrary } from "./MeetingLibrary";

function meeting(changes: Partial<Schemas["MeetingRead"]> = {}) {
  return mapMeeting(meetingRead(changes));
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
      from=""
      to=""
      rangeUnordered={false}
      onQuery={() => {}}
      onStateFilter={() => {}}
      onFrom={() => {}}
      onTo={() => {}}
      onClear={() => {}}
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
  const { container } = renderLibrary(meeting({ processing_state: state }));

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
  renderLibrary(meeting({ processing_state: "queued" }));

  // Act
  const controls = screen.getByRole("listitem").querySelectorAll(`:is(${interactive})`);

  // Assert
  expect(controls).toHaveLength(1);
});

test.for(["recording", "queued", "processing"] as const)(
  "a %s library row has no pause or resume button",
  (state) => {
    // Act
    renderLibrary(meeting({ processing_state: state }));

    // Assert
    expect(screen.queryByRole("button", { name: /pause|resume/i })).not.toBeInTheDocument();
  },
);

test("in-progress library row shows a progress indicator", () => {
  // Act
  renderLibrary(meeting({ processing_state: "queued" }));

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
  const { container } = renderLibrary(meeting({ processing_state: "failed" }));

  // Act
  const chip = container.querySelector(".MuiChip-root");

  // Assert
  expect(chip).toHaveClass("MuiChip-colorError");
});

test("a library with no meetings at all invites an upload", () => {
  // Act
  renderLibrary(meeting(), { meetings: [] });

  // Assert
  expect(screen.getByText("No meetings yet")).toBeInTheDocument();
});

test("a library with no meetings at all does not blame the filters", () => {
  // Act
  renderLibrary(meeting(), { meetings: [] });

  // Assert
  expect(screen.queryByText("No meetings match these filters")).not.toBeInTheDocument();
});

test("a name filter with no match blames the filters", () => {
  // Act
  renderLibrary(meeting(), { meetings: [], query: "retro" });

  // Assert
  expect(screen.getByText("No meetings match these filters")).toBeInTheDocument();
});

test("a state filter with no match among loaded meetings blames the filters", () => {
  // Act
  renderLibrary(meeting(), { stateFilter: "failed" });

  // Assert
  expect(screen.getByText("No meetings match these filters")).toBeInTheDocument();
});

test("the empty result offers to clear the filters", async () => {
  // Arrange
  const onClear = vi.fn();
  renderLibrary(meeting(), { meetings: [], from: "2026-10-01", onClear });

  // Act
  await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));

  // Assert
  expect(onClear).toHaveBeenCalledOnce();
});

test("an unordered range is refused beside the end date", () => {
  // Act
  renderLibrary(meeting(), { from: "2026-10-05", to: "2026-10-04", rangeUnordered: true });

  // Assert
  expect(screen.getByLabelText("To")).toHaveAccessibleDescription(
    "End date is before the start date",
  );
});

test("an unordered range marks the end date invalid", () => {
  // Act
  renderLibrary(meeting(), { from: "2026-10-05", to: "2026-10-04", rangeUnordered: true });

  // Assert
  expect(screen.getByLabelText("To")).toBeInvalid();
});

test("an unordered range does not say that nothing matches", () => {
  // Act
  renderLibrary(meeting(), {
    meetings: [],
    from: "2026-10-05",
    to: "2026-10-04",
    rangeUnordered: true,
  });

  // Assert
  expect(screen.queryByText("No meetings match these filters")).not.toBeInTheDocument();
});

test("an end date alone counts as a filter", () => {
  // Act
  renderLibrary(meeting(), { meetings: [], to: "2026-10-31" });

  // Assert
  expect(screen.getByText("No meetings match these filters")).toBeInTheDocument();
});

test("a year still being typed is not reported", () => {
  // Arrange
  const onFrom = vi.fn();
  renderLibrary(meeting(), { onFrom });

  // Act
  fireEvent.change(screen.getByLabelText("From"), { target: { value: "0002-11-06" } });

  // Assert
  expect(onFrom).not.toHaveBeenCalled();
});

test("a year still being typed stays in the field", () => {
  // Arrange
  renderLibrary(meeting());

  // Act
  fireEvent.change(screen.getByLabelText("From"), { target: { value: "0002-11-06" } });

  // Assert
  expect(screen.getByLabelText("From")).toHaveValue("0002-11-06");
});

test("a cleared date is reported", () => {
  // Arrange
  const onFrom = vi.fn();
  renderLibrary(meeting(), { from: "2026-10-05", onFrom });

  // Act
  fireEvent.change(screen.getByLabelText("From"), { target: { value: "" } });

  // Assert
  expect(onFrom).toHaveBeenCalledWith("");
});

test("a state filter keeps only meetings in that state", () => {
  // Arrange
  const meetings = [
    meeting({ id: "done", name: "Done" }),
    meeting({ id: "failed", name: "Broken", processing_state: "failed" }),
  ];

  // Act
  renderLibrary(meeting(), { meetings, stateFilter: "failed" });

  // Assert
  expect(screen.getAllByRole("listitem").map((row) => row.textContent)).toEqual([
    expect.stringContaining("Broken"),
  ]);
});

test("a blank name filter counts as no filter", () => {
  // Act
  renderLibrary(meeting(), { meetings: [], query: "   " });

  // Assert
  expect(screen.getByText("No meetings yet")).toBeInTheDocument();
});

test("loading shows a spinner instead of an empty state", () => {
  // Act
  renderLibrary(meeting(), { meetings: [], loading: true });

  // Assert
  expect(screen.queryByText("No meetings yet")).not.toBeInTheDocument();
});

test("a failure shows its message instead of an empty state", () => {
  // Act
  renderLibrary(meeting(), { meetings: [], error: "Could not load" });

  // Assert
  expect(screen.getByRole("alert")).toHaveTextContent("Could not load");
});

test("a failure keeps the meetings already loaded", () => {
  // Act
  renderLibrary(meeting(), { error: "Could not refresh" });

  // Assert
  expect(screen.getByText("Weekly sync")).toBeInTheDocument();
});
