import { screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { errorBody, workspaceRead } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { WorkspacePresetSelect } from "./WorkspacePresetSelect";

function answerWorkspace(found: boolean) {
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}", ({ response }) =>
      found
        ? response(200).json(workspaceRead({ default_preset: "interview" }))
        : response(404).json(errorBody("NOT_FOUND", "No such workspace")),
    ),
  );
}

function renderSelect() {
  const onChange = vi.fn();
  const view = renderWithProviders(
    <WorkspacePresetSelect workspaceId="workspace" value={null} onChange={onChange} />,
  );
  return { ...view, onChange };
}

async function openPresets(found: boolean) {
  answerWorkspace(found);
  const view = renderSelect();
  await view.user.click(await screen.findByRole("combobox", { name: "Note preset" }));
  return view;
}

const optionNames = () => screen.getAllByRole("option").map((option) => option.textContent);

test("shows the workspace default as the choice", async () => {
  // Arrange
  answerWorkspace(true);

  // Act
  renderSelect();

  // Assert
  expect(await screen.findByRole("combobox", { name: "Note preset" })).toHaveTextContent(
    "Interview (workspace default)",
  );
});

test("offers every preset", async () => {
  // Act
  await openPresets(true);

  // Assert
  expect(optionNames()).toEqual(["Summary", "Detailed", "Interview (workspace default)"]);
});

test("a chosen preset is reported", async () => {
  // Arrange
  const { user, onChange } = await openPresets(true);

  // Act
  await user.click(screen.getByRole("option", { name: "Detailed" }));

  // Assert
  expect(onChange).toHaveBeenCalledWith("detailed");
});

test("shows progress while the default loads", () => {
  // Arrange
  answerWorkspace(true);

  // Act
  renderSelect();

  // Assert
  expect(screen.getByRole("progressbar", { name: "Loading note preset" })).toBeInTheDocument();
});

test("a failed load shows the API's message", async () => {
  // Arrange
  answerWorkspace(false);

  // Act
  renderSelect();

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("No such workspace");
});

test("a failed load still offers every preset", async () => {
  // Act
  await openPresets(false);

  // Assert
  expect(optionNames()).toEqual(["Summary", "Detailed", "Interview"]);
});
