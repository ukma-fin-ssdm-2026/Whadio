import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { SegmentRow } from "./SegmentRow";

test("the avatar shows the speaker's initials", () => {
  // Act
  render(
    <SegmentRow speaker="Olena Bondar" startSeconds={0}>
      Budget agreed
    </SegmentRow>,
  );

  // Assert
  expect(screen.getByText("OB")).toBeInTheDocument();
});
