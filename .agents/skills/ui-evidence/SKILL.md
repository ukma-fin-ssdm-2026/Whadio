---
name: ui-evidence
description: Screenshot and record the running Whadio web app with Playwright, to check a change visible in the SPA and to attach screenshots or a short video to an issue or pull request. Use it without being asked after changing anything under frontend/ that renders, when reviewing a pull request that touches the SPA, and whenever an issue asks for screenshots or a video.
---

# UI evidence

Check the running web app the way a user sees it, and keep the pictures as evidence.
`frontend/scripts/capture.ts` takes a fixed set of screenshots in one command; `playwright cli`
drives multi-step flows and records videos. Both use Playwright's own Chromium, never a system
browser.

## Rules

- Files go under `.ui-evidence/<task>/` at the repository root, which git ignores. Never commit
  screenshots or videos.
- Show only made-up data: the account below and the content you seed. No real meeting content,
  and no passwords, tokens or `.env` values on screen. The repository is public, and attached files
  open without signing in.
- Look at the key shots yourself before you report: at least the desktop and the phone view of each
  changed screen, in both themes.
- Every console error, uncaught exception or failed request the capture lists is a finding, unless
  you can explain it, such as a `401` from the session check on a signed-out page.
- Post to GitHub only after the user has agreed to the files and the comment.

## 1. Set up once

From `frontend/`: `npm ci` installs Playwright, and `npx playwright install chromium` downloads its
browser into Playwright's cache (`~/.cache/ms-playwright`, or `%LOCALAPPDATA%\ms-playwright` on
Windows).

## 2. Start the app

From the repository root, each in its own terminal or background job:

1. `uv run task infra:up`: PostgreSQL, RabbitMQ, SeaweedFS and Mailpit.
2. `uv run task dev`: the API on port 3000. `http://localhost:3000/health` answers
   `{"status":"ok"}`.
3. The web app, one of:
   - `npm --prefix frontend run dev`: Vite on port 5173 with hot reload, for checks while you work;
   - `npm --prefix frontend run build`, then `npm --prefix frontend run preview`: the production
     build on port 4173, without the dev tools button, for evidence you attach.

Reuse a running server only if it serves your working tree. If a port is taken, append
`-- --port <n> --strictPort` and pass the same address as `--base-url`.

## 3. Capture screens

```bash
npm --prefix frontend run capture -- / /meetings --out <task>/after
```

- It signs in as `ui-evidence@whadio.dev`, a development account it creates or updates with
  `whadio dev-user` from the project's `.venv` under a fresh random password, which it never
  prints. `--signed-out` skips the account, for `/sign-in`.
- It saves `<route>-<width>x<height>-<theme>.png` for every route at 1440 × 900 and 390 × 844, light
  and dark. `--viewport 1440x900` and `--theme dark` narrow that and repeat; `--full-page` captures
  below the fold.
- Under each file it lists the page's console errors and warnings, uncaught exceptions and failed
  requests. At the end it names the session file that `playwright cli` can load.
- `--base-url` points at another server (default `http://127.0.0.1:5173`). `--out` names a folder
  inside `.ui-evidence/`, and the script refuses one outside it.

The account starts with an empty personal workspace. Seed what the screen needs through the SPA in
a CLI session (section 4) or through the API (`docs/api/api-design.md`), with made-up names and
text. An upload stays `queued` until the workers process it (`uv run task workers:up`).

**Before and after.** For a change to an existing screen, capture the base branch as well: add a
worktree of it (`git worktree add ../whadio-base origin/main`), run `npm ci` and the web app there
on another port, and run the capture from your own checkout with `--base-url` at that port and
`--out <task>/before`. Use the same routes and the same data.

## 4. Flows and video

`playwright cli` drives one browser session step by step. Run it from `frontend/`:

```bash
npx playwright cli open --browser=chromium
npx playwright cli state-load ../.ui-evidence/<task>/after/session.json
npx playwright cli resize 1280 800
npx playwright cli goto http://127.0.0.1:5173/meetings
npx playwright cli snapshot
npx playwright cli click e15
npx playwright cli screenshot --filename=../.ui-evidence/<task>/flow-1.png
npx playwright cli close
```

- Always open with `--browser=chromium`; without it the CLI starts the system Chrome.
- `snapshot`, or `find <text>`, lists the page's elements with refs such as `e15` for `click`,
  `fill`, `select` and `upload`.
- `set-color-scheme dark`, `console error` and `requests` check the same things as the capture.
- The session file comes from a capture run; capture any route first if you have none.

To record a video, wrap the steps:

```bash
npx playwright cli video-start ../.ui-evidence/<task>/demo.webm --size 1280x800 --cursor
npx playwright cli video-show-actions
npx playwright cli video-chapter "Rename a speaker" --duration=1500
npx playwright cli video-stop
```

The steps go between `video-chapter` and `video-stop`; a new chapter marks each part of the story.
Keep a video under a minute and under 10 MB, GitHub's limit on free plans. GitHub plays WebM, but
MP4 plays in more browsers; where ffmpeg is installed, convert it with
`ffmpeg -i demo.webm -c:v libx264 -pix_fmt yuv420p -movflags +faststart demo.mp4`.

`npx playwright cli --help` lists every command, and
`frontend/node_modules/playwright-core/lib/tools/skills/playwright-cli/SKILL.md` documents the
installed version in full.

## 5. Attach to GitHub

Write the comment in `.ui-evidence/<task>/comment.md`: one short line per screen naming the route,
the viewport and the theme, then the image as
`![Meetings, 1440 × 900, light](./after/meetings-1440x900-light.png)`, with the path relative to
the comment file. Leave videos out of the body. Once the user agrees, post it with gh 2.99 or newer
(`gh --version`):

```bash
gh issue comment <number> --body-file .ui-evidence/<task>/comment.md --attach .ui-evidence/<task>/after/meetings-1440x900-light.png --attach .ui-evidence/<task>/demo.mp4
```

gh uploads each attached file and points the matching `![…](…)` reference at the upload. It leaves a
bare path as it is, and appends every attached file the body does not reference to the end of the
comment. That is where a video goes: alone in its paragraph, it renders as a player.
`gh pr comment` takes the same flags. Read the posted comment back
(`gh api repos/{owner}/{repo}/issues/comments/<id> --jq .body`) to check that no local path is
left. With an older gh, give the user the paths to drag into the comment instead.

## AI Usage

This skill and `frontend/scripts/capture.ts` were written with Claude Code.
