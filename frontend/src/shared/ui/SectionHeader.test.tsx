import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { SectionHeader } from "./SectionHeader";

test("renders the title as a second-level heading", () => {
  // Act
  render(<SectionHeader title="Workspace library" description="Every meeting" />);

  // Assert
  expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(/^Workspace library$/);
});
