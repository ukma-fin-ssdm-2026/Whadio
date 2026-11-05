import { act, render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { expect, test, vi } from "vitest";
import { App } from "@/app/App";
import { serveApi, stubViewportWidth } from "@/app/testing";
import { AdminPage } from "@/features/admin/AdminPage";
import { ADMIN_KEY } from "@/features/admin/api/monitoring";
import type { Schemas } from "@/shared/api/types";
import { errorBody, page } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { server } from "@/shared/testing/server";

const STAMP = "2026-11-05T10:00:00Z";
function job(changes: Partial<Schemas["JobSnapshot"]> = {}): Schemas["JobSnapshot"] {
  return {
    job_id: "job-1",
    workspace_id: "workspace-alpha",
    job_type: "transcription",
    status: "queued",
    created_at: STAMP,
    queued_at: null,
    started_at: null,
    finished_at: null,
    attempts_started: 0,
    as_of: STAMP,
    queue_wait_seconds: null,
    running_seconds: null,
    last_queue_wait_seconds: null,
    last_attempt_duration_seconds: null,
    total_elapsed_seconds: 10,
    failure_code: null,
    failure_description: null,
    timing_anomaly: false,
    ...changes,
  };
}
const metrics: Schemas["MetricsRead"] = {
  status: "ok",
  generated_at: STAMP,
  jobs: [
    {
      job_type: "transcription",
      queued: 1,
      running: 0,
      failed: 0,
      unpublished: 1,
      oldest_queue_wait_seconds: null,
      unknown_queue_waits: 1,
    },
  ],
};
function serve() {
  server.use(
    http.get("/api/v1/admin/metrics", () => HttpResponse.json(metrics)),
    http.get("/api/v1/admin/jobs", () => HttpResponse.json(page([job()]))),
  );
}
function openPage() {
  serve();
  const onForbidden = vi.fn();
  return {
    ...renderWithProviders(
      <AdminPage filters={{}} onFilters={() => {}} onForbidden={onForbidden} />,
    ),
    onForbidden,
  };
}

test("shows unknown waits separately from zero counts and the server timestamp", async () => {
  // Arrange
  openPage();
  // Act
  await screen.findByText("Workspace: workspace-alpha");
  // Assert
  expect(screen.getByText("Waiting: Unknown · Attempts: 0")).toBeVisible();
  expect(screen.getByText("Unknown queue waits")).toBeVisible();
  expect(screen.getByText(/Counts assembled/)).toBeVisible();
  expect(screen.getAllByText("0")).toHaveLength(2);
});

test("displays a known zero wait as zero", async () => {
  // Arrange
  openPage();
  server.use(
    http.get("/api/v1/admin/jobs", () => HttpResponse.json(page([job({ queue_wait_seconds: 0 })]))),
  );
  // Act
  await screen.findByText(/Waiting: 0m 0s/);
  // Assert
  expect(screen.queryByText("Waiting: Unknown · Attempts: 0")).not.toBeInTheDocument();
});

test.for(["metrics", "jobs"])(
  "a %s refusal removes both snapshots and stops requests",
  async (endpoint) => {
    // Arrange
    const { user, queryClient, onForbidden } = openPage();
    await screen.findByText("Workspace: workspace-alpha");
    server.use(
      http.get(`/api/v1/admin/${endpoint}`, () =>
        HttpResponse.json(errorBody("INSUFFICIENT_ROLE", "Denied"), { status: 403 }),
      ),
    );
    // Act
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText(/Not allowed/);
    // Assert
    expect(screen.queryByText("Workspace: workspace-alpha")).not.toBeInTheDocument();
    expect(screen.queryByText(/Counts assembled/)).not.toBeInTheDocument();
    await waitFor(() => expect(onForbidden).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        queryClient.getQueriesData({ queryKey: ADMIN_KEY }).every(([, data]) => data === undefined),
      ).toBe(true),
    );
  },
);

test("a late successful response cannot restore data after a refusal", async () => {
  // Arrange
  const { user } = openPage();
  await screen.findByText("Workspace: workspace-alpha");
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  server.use(
    http.get("/api/v1/admin/metrics", () => HttpResponse.json({}, { status: 403 })),
    http.get("/api/v1/admin/jobs", async () => {
      await gate;
      return HttpResponse.json(page([job()]));
    }),
  );
  // Act
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  await screen.findByText(/Not allowed/);
  await act(async () => release());
  // Assert
  expect(screen.queryByText("Workspace: workspace-alpha")).not.toBeInTheDocument();
});

test("loads the next opaque cursor and preserves existing jobs", async () => {
  // Arrange
  const { user } = openPage();
  const cursors: (string | null)[] = [];
  server.use(
    http.get("/api/v1/admin/jobs", ({ request }) => {
      const cursor = new URL(request.url).searchParams.get("cursor");
      cursors.push(cursor);
      return HttpResponse.json(
        cursor
          ? page([job({ job_id: "job-2", workspace_id: "workspace-beta" })])
          : page([job()], "opaque-next"),
      );
    }),
  );
  await screen.findByText("Workspace: workspace-alpha");
  // Act
  await user.click(screen.getByRole("button", { name: "Load more" }));
  await screen.findByText("Workspace: workspace-beta");
  // Assert
  expect(cursors).toEqual([null, "opaque-next"]);
  expect(screen.getByText("Workspace: workspace-alpha")).toBeVisible();
});

test("shows running time and only the safe failure description", async () => {
  // Arrange
  openPage();
  server.use(
    http.get("/api/v1/admin/jobs", () =>
      HttpResponse.json(
        page([
          job({ status: "running", running_seconds: 65, attempts_started: 2 }),
          job({ job_id: "failed", status: "failed", failure_description: "Timed out." }),
        ]),
      ),
    ),
  );
  // Act
  await screen.findByText("Timed out.");
  // Assert
  expect(screen.getByText("Running: 1m 5s · Attempts: 2")).toBeVisible();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

test("a transient failure retains the dated snapshot and offers retry", async () => {
  // Arrange
  const { user } = openPage();
  await screen.findByText("Workspace: workspace-alpha");
  server.use(http.get("/api/v1/admin/jobs", () => HttpResponse.json({}, { status: 500 })));
  // Act
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  await screen.findByText(/Jobs could not/);
  // Assert
  expect(screen.getByText("Workspace: workspace-alpha")).toBeVisible();
  expect(screen.getByRole("button", { name: "Retry jobs" })).toBeVisible();
});

test("empty results explain that no jobs match", async () => {
  // Arrange
  openPage();
  server.use(http.get("/api/v1/admin/jobs", () => HttpResponse.json(page([]))));
  // Act
  await screen.findByText("No jobs match these filters.");
  // Assert
  expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
});

async function openApp(administrator: boolean, path = "/admin") {
  stubViewportWidth(1440);
  window.history.replaceState(null, "", path);
  serveApi(true);
  serve();
  server.use(
    http.get("/api/v1/users/me", () =>
      HttpResponse.json({
        id: "member",
        email: "member@example.com",
        name: "Demo Member",
        is_administrator: administrator,
      }),
    ),
  );
  if (!administrator)
    server.use(http.get("/api/v1/admin/jobs", () => HttpResponse.json({}, { status: 403 })));
  render(<App />);
}

test("an administrator sees the Admin entry after a fresh deep link", async () => {
  // Act
  await openApp(true);
  // Assert
  expect(await screen.findByRole("link", { name: "Admin" })).toBeVisible();
  expect(await screen.findByText("Workspace: workspace-alpha")).toBeVisible();
});

test("a member has no Admin entry and the direct link refuses access", async () => {
  // Act
  await openApp(false);
  await screen.findByText(/Not allowed/);
  // Assert
  expect(screen.queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
});

test("filters survive reload and changing one resets paging", async () => {
  // Arrange
  await openApp(true, "/admin?job_type=notes&status=failed");
  const requests: URL[] = [];
  server.use(
    http.get("/api/v1/admin/jobs", ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(page([job()], "next"));
    }),
  );
  await screen.findByText("Workspace: workspace-alpha");
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Load more" }));
  // Act
  await user.click(screen.getByRole("combobox", { name: "State" }));
  await user.click(screen.getByRole("option", { name: "Running" }));
  await waitFor(() =>
    expect(new URL(window.location.href).searchParams.get("status")).toBe("running"),
  );
  // Assert
  expect(requests[0]?.searchParams.get("job_type")).toBe("notes");
  expect(requests.at(-1)?.searchParams.get("cursor")).toBeNull();
  expect(requests.at(-1)?.searchParams.get("status")).toBe("running");
});

test("a monitoring 401 returns to sign in", async () => {
  // Arrange
  await openApp(true);
  await screen.findByText("Workspace: workspace-alpha");
  server.use(
    http.get("/api/v1/admin/jobs", () =>
      HttpResponse.json(errorBody("UNAUTHENTICATED", "Sign in required"), { status: 401 }),
    ),
  );
  // Act
  await userEvent.setup().click(screen.getByRole("button", { name: "Refresh" }));
  // Assert
  expect(await screen.findByRole("button", { name: "Sign in" })).toBeVisible();
  expect(screen.queryByText("Workspace: workspace-alpha")).not.toBeInTheDocument();
});

test("revocation also removes administrator navigation", async () => {
  // Arrange
  await openApp(true);
  await screen.findByRole("link", { name: "Admin" });
  await screen.findByText("Workspace: workspace-alpha");
  server.use(
    http.get("/api/v1/admin/metrics", () => HttpResponse.json({}, { status: 403 })),
    http.get("/api/v1/users/me", () =>
      HttpResponse.json({ id: "member", email: "member@example.com", is_administrator: false }),
    ),
  );
  // Act
  await userEvent.setup().click(screen.getByRole("button", { name: "Refresh" }));
  await screen.findByText(/Not allowed/);
  // Assert
  await waitFor(() =>
    expect(screen.queryByRole("link", { name: "Admin" })).not.toBeInTheDocument(),
  );
});

test("polling fetches fresh metrics and jobs", async () => {
  // Arrange
  const { queryClient } = openPage();
  await screen.findByText("Workspace: workspace-alpha");
  const requests = vi.fn();
  server.use(
    http.get("/api/v1/admin/metrics", () => {
      requests();
      return HttpResponse.json(metrics);
    }),
  );
  // Act
  await waitFor(() => expect(requests).toHaveBeenCalled(), { timeout: 12_000 });
  // Assert
  expect(queryClient.getQueryData([...ADMIN_KEY, "metrics"])).toEqual(metrics);
}, 15_000);

test("browser back restores the previous URL filters", async () => {
  // Arrange
  await openApp(true, "/admin?job_type=notes&status=failed");
  await screen.findByText("Workspace: workspace-alpha");
  const user = userEvent.setup();
  await user.click(screen.getByRole("combobox", { name: "State" }));
  await user.click(screen.getByRole("option", { name: "Running" }));
  await waitFor(() => expect(window.location.search).toContain("status=running"));
  // Act
  window.history.back();
  // Assert
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: "State" })).toHaveTextContent("Failed"),
  );
  expect(window.location.search).toContain("job_type=notes");
});
