import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

let server;
let ExportControls;
let ExportDownloadMenu;

before(async () => {
  server = await createServer({
    server: { middlewareMode: true, watch: null },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
    ssr: { noExternal: ["@mui/icons-material"] },
  });
  ({ ExportControls, ExportDownloadMenu } = await server.ssrLoadModule("/src/main.jsx"));
});

after(async () => {
  await server?.close();
});

function render(changes = {}) {
  return renderToStaticMarkup(
    createElement(ExportControls, {
      meetingId: "meeting",
      tab: "transcript",
      transcript: { revision: { revision_type: "edited" } },
      notes: null,
      loading: false,
      ...changes,
    }),
  );
}

function menu(tab, revisionType = "edited") {
  return renderToStaticMarkup(
    createElement(ExportDownloadMenu, {
      meetingId: "meeting",
      tab,
      transcript: { revision: { revision_type: revisionType } },
    }),
  );
}

test("transcript download is a compact menu button", () => {
  assert.match(render(), /aria-label="Download transcript"[^>]*aria-haspopup="menu"/);
});

test("download formats stay hidden until the menu is opened", () => {
  assert.ok(!render().includes("Markdown"));
});

for (const [revision, version] of [
  ["edited", "current"],
  ["original", "original"],
]) {
  test(`${revision} transcript menu downloads the displayed version in every format`, () => {
    const html = menu("transcript", revision);
    for (const query of [
      `format=markdown&amp;version=${version}&amp;timestamps=true`,
      `format=markdown&amp;version=${version}&amp;timestamps=false`,
      `format=vtt&amp;version=${version}`,
    ]) {
      assert.ok(html.includes(`/api/v1/meetings/meeting/transcript/export?${query}`));
    }
  });
}

test("notes menu offers only Markdown notes", () => {
  const html = menu("notes");
  assert.ok(html.includes('href="/api/v1/meetings/meeting/notes/export"'));
  assert.ok(!html.includes("transcript/export"));
});

test("notes download is hidden until notes exist", () => {
  assert.equal(render({ tab: "notes" }), "");
});

test("notes tab offers its download when saved notes exist", () => {
  assert.ok(
    render({ tab: "notes", notes: { content: "Saved notes" } }).includes(
      'aria-label="Download notes"',
    ),
  );
});

test("transcript tab does not offer notes downloads when the transcript is missing", () => {
  assert.equal(render({ transcript: null, notes: { content: "Saved notes" } }), "");
});

test("recording tab has no transcript or notes download button", () => {
  assert.equal(render({ tab: "recording", notes: { content: "Saved notes" } }), "");
});

test("download is hidden while content loads", () => {
  assert.equal(render({ loading: true }), "");
});
