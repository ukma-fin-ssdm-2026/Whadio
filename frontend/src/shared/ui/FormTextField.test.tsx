import { zodResolver } from "@hookform/resolvers/zod";
import { render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { useForm } from "react-hook-form";
import { expect, test, vi } from "vitest";
import { z } from "zod";
import { FormTextField } from "./FormTextField";

const schema = z.object({ name: z.string().min(1, "Enter a name") });

function NameForm({ onValid }: { onValid: (values: z.output<typeof schema>) => void }) {
  const { control, handleSubmit } = useForm({
    resolver: zodResolver(schema),
    defaultValues: { name: "" },
  });
  return (
    <form noValidate onSubmit={handleSubmit(onValid)}>
      <FormTextField control={control} name="name" label="Name" helperText="Shown to members" />
      <button type="submit">Save</button>
    </form>
  );
}

function renderForm() {
  const onValid = vi.fn();
  render(<NameForm onValid={onValid} />);
  return { onValid, user: userEvent.setup() };
}

test("shows the helper text while the field is valid", () => {
  // Act
  renderForm();

  // Assert
  expect(screen.getByLabelText("Name")).toHaveAccessibleDescription("Shown to members");
});

test("shows the validation error in place of the helper text", async () => {
  // Arrange
  const { user } = renderForm();

  // Act
  await user.click(screen.getByRole("button", { name: "Save" }));

  // Assert
  expect(screen.getByLabelText("Name")).toHaveAccessibleDescription("Enter a name");
});

test("marks the field invalid after a failed submit", async () => {
  // Arrange
  const { user } = renderForm();

  // Act
  await user.click(screen.getByRole("button", { name: "Save" }));

  // Assert
  expect(screen.getByLabelText("Name")).toBeInvalid();
});

test("submits what was typed", async () => {
  // Arrange
  const { onValid, user } = renderForm();
  await user.type(screen.getByLabelText("Name"), "Standup");

  // Act
  await user.click(screen.getByRole("button", { name: "Save" }));

  // Assert
  expect(onValid).toHaveBeenCalledWith({ name: "Standup" }, expect.anything());
});
