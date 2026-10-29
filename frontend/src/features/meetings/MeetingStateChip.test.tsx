import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { MeetingStateChip } from "./MeetingStateChip";

test.for([
  ["recording", "Recording"],
  ["queued", "Queued"],
  ["processing", "Processing"],
  ["failed", "Failed"],
] as const)("%s meeting is labelled %s", ([state, label]) => {
  // Act
  const { container } = render(<MeetingStateChip state={state} />);

  // Assert
  expect(container).toHaveTextContent(new RegExp(`^${label}$`));
});

test("in-progress meeting shows a progress indicator", () => {
  // Act
  render(<MeetingStateChip state="queued" />);

  // Assert
  expect(screen.getByRole("progressbar")).toBeInTheDocument();
});

test("failed meeting is an error chip", () => {
  // Act
  const { container } = render(<MeetingStateChip state="failed" />);

  // Assert
  expect(container.firstChild).toHaveClass("MuiChip-colorError");
});

test("failed meeting shows no progress indicator", () => {
  // Act
  render(<MeetingStateChip state="failed" />);

  // Assert
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
});

test("processed meeting shows no state", () => {
  // Act
  const { container } = render(<MeetingStateChip state="processed" />);

  // Assert
  expect(container).toBeEmptyDOMElement();
});
