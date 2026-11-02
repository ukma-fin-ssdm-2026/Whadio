import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdirSync } from "node:fs";
import { join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { type Browser, chromium, type Page } from "playwright";

const USAGE = `Usage: npm run capture -- <route>... --out <folder in .ui-evidence> [--base-url <url>]
       [--viewport <WxH>]... [--theme light|dark]... [--full-page] [--signed-out]`;
const REPO_ROOT = fileURLToPath(new URL("../..", import.meta.url));
const EVIDENCE_ROOT = join(REPO_ROOT, ".ui-evidence");
// The project's own entry point by absolute path, so no PATH lookup decides what runs.
const WHADIO_CLI =
  process.platform === "win32"
    ? join(REPO_ROOT, ".venv", "Scripts", "whadio.exe")
    : join(REPO_ROOT, ".venv", "bin", "whadio");
const ACCOUNT = { email: "ui-evidence@whadio.dev", name: "UI Evidence" };
const THEMES = ["light", "dark"] as const;

type Theme = (typeof THEMES)[number];
type Viewport = { width: number; height: number };

function fail(message: string): never {
  console.error(`${message}\n${USAGE}`);
  process.exit(2);
}

function parseViewport(value: string): Viewport {
  const [, width, height] = /^(\d+)x(\d+)$/.exec(value) ?? [];
  if (width === undefined || height === undefined) fail(`Bad --viewport "${value}"`);
  return { width: Number(width), height: Number(height) };
}

function parseTheme(value: string): Theme {
  return THEMES.find((theme) => theme === value) ?? fail(`Bad --theme "${value}"`);
}

function outputFolder(name: string) {
  const folder = resolve(EVIDENCE_ROOT, name);
  if (!folder.startsWith(EVIDENCE_ROOT + sep)) fail("--out must stay inside .ui-evidence/");
  return folder;
}

function parseOptions() {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      out: { type: "string" },
      "base-url": { type: "string", default: "http://127.0.0.1:5173" },
      viewport: { type: "string", multiple: true, default: ["1440x900", "390x844"] },
      theme: { type: "string", multiple: true, default: [...THEMES] },
      "full-page": { type: "boolean", default: false },
      "signed-out": { type: "boolean", default: false },
    },
  });
  if (positionals.length === 0) fail("Name at least one route, such as /meetings");
  if (values.out === undefined) fail("--out is required");
  return {
    routes: positionals,
    out: outputFolder(values.out),
    baseUrl: values["base-url"],
    viewports: values.viewport.map(parseViewport),
    themes: values.theme.map(parseTheme),
    fullPage: values["full-page"],
    signedOut: values["signed-out"],
  };
}

function resetAccountPassword(): string {
  const password = randomBytes(18).toString("base64url");
  const result = spawnSync(
    WHADIO_CLI,
    ["dev-user", "--email", ACCOUNT.email, "--name", ACCOUNT.name, "--password", password],
    { cwd: REPO_ROOT, stdio: ["ignore", "ignore", "inherit"] },
  );
  if (result.status !== 0) {
    fail(`${WHADIO_CLI} dev-user failed (${result.error?.message ?? `exit ${result.status}`})`);
  }
  return password;
}

async function signIn(browser: Browser, baseUrl: string, password: string, statePath: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(new URL("/sign-in", baseUrl).href);
  await page.getByLabel(/^Email/).fill(ACCOUNT.email);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => url.pathname !== "/sign-in");
  await context.storageState({ path: statePath });
  await context.close();
}

async function capture(page: Page, url: string, file: string, fullPage: boolean) {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      problems.push(`console.${message.type()}: ${message.text()} (${message.location().url})`);
    }
  });
  page.on("pageerror", (error) => problems.push(`exception: ${error.message}`));
  page.on("requestfailed", (request) => {
    problems.push(
      `request failed: ${request.method()} ${request.url()} ${request.failure()?.errorText}`,
    );
  });
  await page.goto(url, { waitUntil: "networkidle" });
  await page.screenshot({ path: file, fullPage });
  return problems;
}

function slug(route: string) {
  return route.replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "") || "home";
}

const options = parseOptions();
mkdirSync(options.out, { recursive: true });
const statePath = join(options.out, "session.json");
const password = options.signedOut ? undefined : resetAccountPassword();
const browser = await chromium.launch();
try {
  if (password !== undefined) await signIn(browser, options.baseUrl, password, statePath);
  let flagged = 0;
  for (const viewport of options.viewports) {
    for (const theme of options.themes) {
      const context = await browser.newContext({
        viewport,
        colorScheme: theme,
        storageState: password === undefined ? undefined : statePath,
      });
      for (const route of options.routes) {
        const file = join(
          options.out,
          `${slug(route)}-${viewport.width}x${viewport.height}-${theme}.png`,
        );
        const page = await context.newPage();
        const problems = await capture(
          page,
          new URL(route, options.baseUrl).href,
          file,
          options.fullPage,
        );
        console.log(`saved ${file}`);
        for (const problem of problems) console.log(`  ${problem}`);
        if (problems.length > 0) flagged += 1;
        await page.close();
      }
      await context.close();
    }
  }
  const total = options.routes.length * options.viewports.length * options.themes.length;
  console.log(`${flagged} of ${total} captures reported problems`);
  if (password !== undefined) console.log(`session for playwright cli state-load: ${statePath}`);
} finally {
  await browser.close();
}
