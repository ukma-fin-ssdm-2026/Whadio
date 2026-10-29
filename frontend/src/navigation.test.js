import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { openAppEnvironment } from "./app-test-environment.js";

let environment;
let App;
let act;
let createElement;
let createRoot;

before(async () => {
  environment = await openAppEnvironment(
    "https://app.example/whadio/meetings/meeting?revision_id=original",
  );
  ({ act, createElement, createRoot } = environment);
  ({ App } = environment.app);
});

after(async () => {
  await environment?.close();
});

function apiResponses(initiallyAuthenticated) {
  let authenticated = initiallyAuthenticated;
  const requests = [];
  const fetch = async (input, options) => {
    const url = new URL(input, window.location.origin);
    requests.push(`${options?.method ?? "GET"} ${url.pathname}${url.search}`);
    let body;
    let status = 200;
    if (url.pathname === "/api/v1/sessions") {
      assert.deepEqual(JSON.parse(options.body), {
        email: "member@example.com",
        password: "test-password",
        kind: "browser",
      });
      authenticated = true;
      body = { user: { id: "member", email: "member@example.com", name: "Demo Member" } };
    } else if (!authenticated) {
      status = 401;
      body = { error: { code: "UNAUTHENTICATED", message: "Sign in required" } };
    } else if (url.pathname === "/api/v1/workspaces") {
      body = {
        items: [
          {
            id: "workspace",
            name: "Demo Workspace",
            my_role: "Owner",
            member_count: 1,
            notes_provider: "Whadio",
          },
        ],
      };
    } else if (url.pathname === "/api/v1/workspaces/workspace") {
      body = { default_preset: "summary" };
    } else if (url.pathname === "/api/v1/workspaces/workspace/meetings") {
      body = { items: [] };
    } else if (url.pathname === "/api/v1/meetings/meeting") {
      body = {
        id: "meeting",
        workspace_id: "workspace",
        name: "Linked meeting outside the first page",
        recorded_at: "2026-10-25T10:00:00Z",
        processing_state: "processed",
        duration_seconds: 5,
        source_type: "upload",
      };
    } else if (url.pathname === "/api/v1/meetings/meeting/notes") {
      body = { items: [] };
    } else if (url.pathname === "/api/v1/meetings/meeting/transcript") {
      const original = url.searchParams.get("revision_id") === "original";
      body = {
        revision: {
          id: original ? "original" : "edited",
          revision_type: original ? "original" : "edited",
        },
        original_revision_id: "original",
        is_edited: true,
        speakers: [{ id: "speaker", display_name: "Demo speaker" }],
        segments: [
          {
            id: "segment",
            speaker_id: "speaker",
            start_seconds: 0,
            end_seconds: 5,
            text: original ? "Original uncorrected wording" : "Current corrected wording",
          },
        ],
      };
    } else {
      throw new Error(`Unexpected API request: ${url.pathname}`);
    }
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
  return { fetch, requests };
}

function button(label) {
  const found = [...document.querySelectorAll("button")].find(
    (item) => item.textContent.trim() === label,
  );
  assert.ok(found, `Expected button: ${label}`);
  return found;
}

async function waitFor(check) {
  const deadline = Date.now() + 3000;
  while (!check() && Date.now() < deadline) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
  }
  assert.ok(check(), "Expected application content before the timeout");
}
for (const authenticated of [true, false]) {
  test(`original deep link survives ${authenticated ? "an existing session" : "sign-in"}, revision switching and Back`, async (context) => {
    window.history.replaceState(null, "", "/whadio/meetings/meeting?revision_id=original");
    sessionStorage.clear();
    const api = apiResponses(authenticated);
    context.mock.method(globalThis, "fetch", api.fetch);
    const root = createRoot(document.getElementById("root"));
    try {
      await act(async () => {
        root.render(createElement(App));
      });
      if (!authenticated) {
        assert.ok(document.querySelector('input[type="email"]'));
        assert.ok(!document.body.textContent.includes("Original uncorrected wording"));
        assert.ok(!api.requests.some((request) => request.includes("/transcript")));
        assert.equal(window.location.search, "?revision_id=original");
        await act(async () => {
          for (const [type, value] of [
            ["email", "member@example.com"],
            ["password", "test-password"],
          ]) {
            const input = document.querySelector(`input[type="${type}"]`);
            const setter = Object.getOwnPropertyDescriptor(
              window.HTMLInputElement.prototype,
              "value",
            ).set;
            setter.call(input, value);
            input.dispatchEvent(new window.Event("input", { bubbles: true }));
          }
        });
        await act(async () => {
          button("Sign in").click();
        });
      }
      await waitFor(() => document.body.textContent.includes("Original uncorrected wording"));
      assert.equal(
        window.location.pathname + window.location.search,
        "/whadio/meetings/meeting?revision_id=original",
      );
      assert.ok(
        api.requests.includes("GET /api/v1/meetings/meeting/transcript?revision_id=original"),
      );
      assert.ok(!document.body.textContent.includes("Current corrected wording"));
      assert.equal(
        document.querySelector('[role="tab"][aria-selected="true"]').textContent,
        "Transcript",
      );

      await act(async () => {
        button("View current transcript").click();
      });
      await waitFor(() => document.body.textContent.includes("Current corrected wording"));
      assert.equal(window.location.pathname + window.location.search, "/whadio/meetings/meeting");
      assert.ok(api.requests.includes("GET /api/v1/meetings/meeting/transcript"));
      assert.ok(!document.body.textContent.includes("Original uncorrected wording"));

      await act(async () => {
        button("View original transcript").click();
      });
      await waitFor(() => document.body.textContent.includes("Original uncorrected wording"));
      assert.equal(window.location.search, "?revision_id=original");

      await act(async () => {
        const popped = new Promise((resolve) =>
          window.addEventListener("popstate", resolve, { once: true }),
        );
        window.history.back();
        await popped;
      });
      await waitFor(() => document.body.textContent.includes("Current corrected wording"));
      assert.equal(window.location.pathname + window.location.search, "/whadio/meetings/meeting");
      assert.ok(!document.body.textContent.includes("Original uncorrected wording"));
    } finally {
      await act(async () => {
        root.unmount();
      });
    }
  });
}
