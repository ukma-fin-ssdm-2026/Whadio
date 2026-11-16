// @vitest-environment jsdom

import { destinations, signedIn } from "./api.js";
import popupHtml from "./popup.html?raw";

vi.mock("./api.js", () => ({
  destinations: vi.fn(),
  signedIn: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));

test("popup lists every destination and preserves a selection beyond the first page", async () => {
  // Arrange
  document.body.innerHTML = popupHtml;
  globalThis.chrome = {
    storage: {
      session: { get: vi.fn(async () => ({ name: "Alice" })) },
      local: {
        get: vi.fn(async () => ({ destination: { folder_id: "later" } })),
        set: vi.fn(),
      },
    },
    tabs: { query: vi.fn(async () => []) },
  };
  signedIn.mockResolvedValue(true);
  destinations.mockResolvedValue([
    {
      workspace_id: "one",
      name: "Personal",
      is_personal: true,
      folders: [{ id: "default", name: "General", is_default: true }],
    },
    { workspace_id: "two", name: "Team", folders: [{ id: "later", name: "Meetings" }] },
  ]);
  // Act
  await import("./popup.js");
  // Assert
  const select = document.getElementById("destination");
  expect({
    labels: [...select.options].map((option) => option.text),
    selected: JSON.parse(select.value),
  }).toEqual({
    labels: ["Personal / General", "Team / Meetings"],
    selected: { workspace_id: "two", folder_id: "later" },
  });
});
