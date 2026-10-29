import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { expect, test } from "vitest";
import { ExportControls, ExportDownloadMenu } from "./App";

function renderControls(changes: Partial<ComponentProps<typeof ExportControls>> = {}) {
  return render(
    <ExportControls
      meetingId="meeting"
      tab="transcript"
      transcript={{ revision: { revision_type: "edited" } }}
      notes={null}
      loading={false}
      {...changes}
    />,
  );
}

function menuLinks(tab: string, revisionType = "edited") {
  render(
    <ExportDownloadMenu
      meetingId="meeting"
      tab={tab}
      transcript={{ revision: { revision_type: revisionType } }}
      onDownload={() => {}}
    />,
  );
  return screen.getAllByRole("menuitem").map((item) => item.getAttribute("href"));
}

test("transcript download is a compact menu button", () => {
  // Act
  renderControls();

  // Assert
  expect(screen.getByRole("button", { name: "Download transcript" })).toHaveAttribute(
    "aria-haspopup",
    "menu",
  );
});

test("download formats stay hidden until the menu is opened", () => {
  // Act
  renderControls();

  // Assert
  expect(screen.queryByText(/Markdown/)).not.toBeInTheDocument();
});

test.for([
  ["edited", "current"],
  ["original", "original"],
] as const)(
  "%s transcript menu downloads the displayed version in every format",
  ([revision, version]) => {
    // Act
    const links = menuLinks("transcript", revision);

    // Assert
    expect(links).toEqual(
      [
        `format=markdown&version=${version}&timestamps=false`,
        `format=markdown&version=${version}&timestamps=true`,
        `format=vtt&version=${version}`,
      ].map((query) => `/api/v1/meetings/meeting/transcript/export?${query}`),
    );
  },
);

test("notes menu offers only Markdown notes", () => {
  // Act
  const links = menuLinks("notes");

  // Assert
  expect(links).toEqual(["/api/v1/meetings/meeting/notes/export"]);
});

test("notes download is hidden until notes exist", () => {
  // Act
  const { container } = renderControls({ tab: "notes" });

  // Assert
  expect(container).toBeEmptyDOMElement();
});

test("notes tab offers its download when saved notes exist", () => {
  // Act
  renderControls({ tab: "notes", notes: { content: "Saved notes" } });

  // Assert
  expect(screen.getByRole("button", { name: "Download notes" })).toBeInTheDocument();
});

test.for([
  [
    "transcript tab does not offer notes downloads when the transcript is missing",
    { transcript: null, notes: { content: "Saved notes" } },
  ],
  [
    "recording tab has no transcript or notes download button",
    { tab: "recording", notes: { content: "Saved notes" } },
  ],
  ["download is hidden while content loads", { loading: true }],
] as const)("%s", ([, changes]) => {
  // Act
  const { container } = renderControls(changes);

  // Assert
  expect(container).toBeEmptyDOMElement();
});
