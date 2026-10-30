import { render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { expect, test } from "vitest";
import { noteRead, transcriptRead } from "@/shared/testing/fixtures";
import { ExportMenu } from "./ExportMenu";

function transcriptOf(revisionType: "original" | "edited") {
  return transcriptRead({
    revision: { ...transcriptRead().revision, revision_type: revisionType },
  });
}

function renderMenu(changes: Partial<ComponentProps<typeof ExportMenu>> = {}) {
  return render(
    <ExportMenu
      meetingId="meeting"
      tab="transcript"
      transcript={transcriptOf("edited")}
      notes={null}
      {...changes}
    />,
  );
}

async function openedMenu(name: string, changes: Partial<ComponentProps<typeof ExportMenu>> = {}) {
  const user = userEvent.setup();
  renderMenu(changes);
  await user.click(screen.getByRole("button", { name }));
  return user;
}

const links = () => screen.getAllByRole("menuitem").map((item) => item.getAttribute("href"));

test("transcript download is a compact menu button", () => {
  // Act
  renderMenu();

  // Assert
  expect(screen.getByRole("button", { name: "Download transcript" })).toHaveAttribute(
    "aria-haspopup",
    "menu",
  );
});

test("download formats stay hidden until the menu is opened", () => {
  // Act
  renderMenu();

  // Assert
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

test("the opened menu is named after what it downloads", async () => {
  // Act
  await openedMenu("Download transcript");

  // Assert
  expect(screen.getByRole("menu")).toHaveAccessibleName("Current transcript download formats");
});

test("the transcript menu names its formats", async () => {
  // Act
  await openedMenu("Download transcript");

  // Assert
  expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual([
    "Markdown (.md)",
    "Markdown with timestamps (.md)",
    "WebVTT (.vtt)",
  ]);
});

test.for([
  ["edited", "current"],
  ["original", "original"],
] as const)(
  "%s transcript menu downloads the displayed version in every format",
  async ([revision, version]) => {
    // Act
    await openedMenu("Download transcript", { transcript: transcriptOf(revision) });

    // Assert
    expect(links()).toEqual(
      [
        `format=markdown&version=${version}&timestamps=false`,
        `format=markdown&version=${version}&timestamps=true`,
        `format=vtt&version=${version}`,
      ].map((query) => `/api/v1/meetings/meeting/transcript/export?${query}`),
    );
  },
);

test("notes menu offers only Markdown notes", async () => {
  // Act
  await openedMenu("Download notes", { tab: "notes", notes: noteRead() });

  // Assert
  expect(links()).toEqual(["/api/v1/meetings/meeting/notes/export"]);
});

test("choosing a format closes the menu", async () => {
  // Arrange
  const user = await openedMenu("Download notes", { tab: "notes", notes: noteRead() });

  // Act
  await user.click(screen.getByRole("menuitem"));

  // Assert
  await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
});

test("Escape closes the menu and returns to its button", async () => {
  // Arrange
  const user = await openedMenu("Download transcript");

  // Act
  await user.keyboard("{Escape}");

  // Assert
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Download transcript" })).toHaveFocus(),
  );
});

test("notes download is hidden until notes exist", () => {
  // Act
  const { container } = renderMenu({ tab: "notes" });

  // Assert
  expect(container).toBeEmptyDOMElement();
});

test.for([
  [
    "transcript tab does not offer notes downloads when the transcript is missing",
    { transcript: null, notes: noteRead() },
  ],
  [
    "recording tab has no transcript or notes download button",
    { tab: "recording", notes: noteRead() },
  ],
] as const)("%s", ([, changes]) => {
  // Act
  const { container } = renderMenu(changes);

  // Assert
  expect(container).toBeEmptyDOMElement();
});
