import assert from "node:assert/strict";
import { mkdtemp, readFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "../../frontend/node_modules/playwright/index.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const profile = await mkdtemp(resolve(tmpdir(), "whadio-recovery-"));
const evidence = resolve(root, ".ui-evidence/f4");
await mkdir(evidence, { recursive: true });
const errors = [];

async function launch() {
  const context = await chromium.launchPersistentContext(profile, {
    channel: "chromium",
    headless: true,
    args: [
      "--no-sandbox",
      `--disable-extensions-except=${resolve(root, "extension")}`,
      `--load-extension=${resolve(root, "extension")}`,
    ],
  });
  const worker = context.serviceWorkers()[0] ?? await context.waitForEvent("serviceworker");
  return { context, worker, id: new URL(worker.url()).host };
}

let running = await launch();
try {
  const seed = await running.context.newPage();
  await seed.goto(`chrome-extension://${running.id}/popup.html`);
  await seed.evaluate(async () => {
    const { recoveryStore } = await import("./recovery-store.js");
    const owner = { server: "https://whadio.example", userId: "original" };
    await recoveryStore.put({ id: "restart-check", owner, startedAt: 1_793_876_400_000, slices: [btoa("synthetic-audio")] });
    await recoveryStore.put({ id: "discard-check", owner, startedAt: 1_793_876_460_000, slices: [btoa("second-synthetic-audio")] });
  });
  await running.context.close();
  running = await launch();
  const page = await running.context.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`chrome-extension://${running.id}/popup.html`);
  await page.getByText("Sign in to the original account and server to recover your saved recordings.", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Retry download" }).count(), 0);
  await page.evaluate(async () => {
    await chrome.storage.session.set({ server: "https://whadio.example", userId: "other", token: "synthetic", expiresAt: new Date(Date.now() + 3600000).toISOString() });
  });
  await page.waitForFunction(() => document.getElementById("recovery").hidden);
  await page.evaluate(async () => {
    await chrome.storage.session.set({ userId: "original" });
  });
  await page.getByRole("heading", { name: "Recordings to save" }).waitFor();
  const restored = await page.evaluate(async () => {
    const { recoveryStore } = await import("./recovery-store.js");
    return recoveryStore.get("restart-check");
  });
  assert.deepEqual(restored.slices, [Buffer.from("synthetic-audio").toString("base64")]);
  assert.equal(await page.getByRole("button", { name: "Retry download" }).count(), 2);
  await page.route("https://whadio.example/**", (route) => route.abort());
  await page.reload();
  await page.getByRole("button", { name: "Retry download" }).first().waitFor();
  await page.locator("body").screenshot({ path: resolve(evidence, "recovery-after-restart.png") });

  await page.getByRole("button", { name: "Retry download" }).first().click();
  await page.waitForFunction(() => document.querySelectorAll("#recovery-list li").length === 1);
  const downloads = await page.evaluate(() => chrome.downloads.search({}));
  assert.equal(downloads.length, 1);
  assert.equal(downloads[0].state, "complete");
  assert.equal((await readFile(downloads[0].filename)).toString(), "synthetic-audio");

  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Discard", exact: true }).click();
  assert.equal(await page.getByRole("button", { name: "Discard", exact: true }).count(), 1);
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Discard", exact: true }).click();
  await page.waitForFunction(() => document.getElementById("recovery").hidden);

  await running.context.close();
  running = await launch();
  const final = await running.context.newPage();
  await final.goto(`chrome-extension://${running.id}/popup.html`);
  const remaining = await final.evaluate(async () => {
    const { recoveryStore } = await import("./recovery-store.js");
    return recoveryStore.list();
  });
  assert.deepEqual(remaining, []);
  assert.deepEqual(errors, []);
  console.log("PASS: real extension IndexedDB survives Chromium restart; popup retry downloads the original audio; discard is confirmed and both removals survive restart.");
} finally {
  await running.context.close();
}
