import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { SettingsRow } from "./SettingsRow";

test("names the setting with a third-level heading", () => {
  // Act
  render(<SettingsRow title="Notes provider" description="Used for notes." control="Whadio" />);

  // Assert
  expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(/^Notes provider$/);
});

test("renders the control beside the description", () => {
  // Act
  render(
    <SettingsRow
      title="Notes provider"
      description="Used for notes."
      control={<button type="button">Change</button>}
    />,
  );

  // Assert
  expect(screen.getByRole("button", { name: "Change" })).toBeInTheDocument();
});
