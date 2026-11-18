import { screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { NotesRegeneration } from "@/shared/api/types";
import { errorBody, notesJobRead } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { type PresetFieldProps, RegenerateNotesDialog } from "./RegenerateNotesDialog";

const PRESET_CHOICES = ["summary", "detailed", "interview"] as const;

function NativePresetField({ value, onChange }: PresetFieldProps) {
  return (
    <select
      aria-label="Note preset"
      value={value ?? ""}
      onChange={(event) => {
        const preset = PRESET_CHOICES.find((item) => item === event.target.value);
        if (preset) onChange(preset);
      }}
    >
      <option value="">Workspace default</option>
      {PRESET_CHOICES.map((preset) => (
        <option key={preset} value={preset}>
          {preset}
        </option>
      ))}
    </select>
  );
}

function serveRegeneration() {
  const bodies: (NotesRegeneration | null | undefined)[] = [];
  server.use(
    http.post("/api/v1/meetings/{meeting_id}/notes", async ({ request, response }) => {
      bodies.push(await request.json());
      return response(202).json(notesJobRead());
    }),
  );
  return bodies;
}

function refuseRegeneration(status: 409 | 503, code: Parameters<typeof errorBody>[0]) {
  server.use(
    http.post("/api/v1/meetings/{meeting_id}/notes", ({ response }) =>
      response(status).json(errorBody(code, `${code} message`)),
    ),
  );
}

function renderDialog() {
  const onClose = vi.fn();
  const view = renderWithProviders(
    <RegenerateNotesDialog
      meeting={{ id: "meeting", workspaceId: "workspace" }}
      renderPresetField={(field) => <NativePresetField {...field} />}
      onClose={onClose}
    />,
  );
  return { ...view, onClose };
}

async function regenerate() {
  const view = renderDialog();
  await view.user.click(screen.getByRole("button", { name: "Regenerate" }));
  return view;
}

test("regenerating without a choice sends no preset", async () => {
  // Arrange
  const bodies = serveRegeneration();

  // Act
  await regenerate();

  // Assert
  await waitFor(() => expect(bodies).toEqual([{}]));
});

test("regenerating with a chosen preset sends it", async () => {
  // Arrange
  const bodies = serveRegeneration();
  const { user } = renderDialog();
  await user.selectOptions(screen.getByLabelText("Note preset"), "detailed");

  // Act
  await user.click(screen.getByRole("button", { name: "Regenerate" }));

  // Assert
  await waitFor(() => expect(bodies).toEqual([{ preset: "detailed" }]));
});

test.for([
  [409, "REGENERATION_LIMIT"],
  [409, "NOTES_IN_PROGRESS"],
  [409, "NOT_TRANSCRIBED"],
  [503, "INTEGRATION_UNAVAILABLE"],
] as const)("a refusal with %i %s shows the server's message", async ([status, code]) => {
  // Arrange
  refuseRegeneration(status, code);

  // Act
  await regenerate();

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent(`${code} message`);
});

test("a refused regeneration keeps the dialog open", async () => {
  // Arrange
  refuseRegeneration(409, "REGENERATION_LIMIT");

  // Act
  const { onClose } = await regenerate();
  await screen.findByRole("alert");

  // Assert
  expect(onClose).not.toHaveBeenCalled();
});

test("a queued regeneration closes the dialog", async () => {
  // Arrange
  serveRegeneration();

  // Act
  const { onClose } = await regenerate();

  // Assert
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
});

test("a queued regeneration says the notes are being regenerated", async () => {
  // Arrange
  serveRegeneration();

  // Act
  await regenerate();

  // Assert
  expect(await screen.findByText("Regenerating the notes.")).toBeInTheDocument();
});

test("cancelling sends no request", async () => {
  // Arrange
  const bodies = serveRegeneration();
  const { user } = renderDialog();

  // Act
  await user.click(screen.getByRole("button", { name: "Cancel" }));

  // Assert
  expect(bodies).toEqual([]);
});
