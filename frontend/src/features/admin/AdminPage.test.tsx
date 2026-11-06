import { act, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, expect, test, vi } from "vitest";
import { errorBody, page } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { server } from "@/shared/testing/server";
import { AdminPage } from "./AdminPage";
import { ADMIN_KEY, MONITOR_INTERVAL_MS } from "./api/monitoring";
import { job, metrics, STAMP, serve } from "./testing";

afterEach(() => vi.useRealTimers());

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

const countValue = (label: string) =>
  within(screen.getByRole("table", { name: "Job counts by type" }))
    .getByText(label)
    .closest("th")?.nextElementSibling;

test("shows an unknown current job wait", async () => {
  // Arrange
  openPage();
  // Act
  const timing = await screen.findByText("Waiting: Unknown · Attempts: 0");
  // Assert
  expect(timing).toBeVisible();
});

test("shows the server assembly timestamp", async () => {
  // Arrange
  openPage();
  // Act
  const stamp = await screen.findByText(`Counts assembled ${new Date(STAMP).toLocaleString()}`);
  // Assert
  expect(stamp).toBeVisible();
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

test.for(["metrics", "jobs"])("a %s refusal removes both snapshots", async (endpoint) => {
  // Arrange
  const { user } = openPage();
  await screen.findByRole("button", { name: "Copy workspace ID workspace-alpha" });
  server.use(
    http.get(`/api/v1/admin/${endpoint}`, () =>
      HttpResponse.json(errorBody("INSUFFICIENT_ROLE", "Denied"), { status: 403 }),
    ),
  );
  // Act
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  await screen.findByText(/Not allowed/);
  // Assert
  expect(screen.queryAllByText(/Job: job-1|Counts assembled/)).toHaveLength(0);
});

test.for(["metrics", "jobs"])("a %s refusal clears monitoring caches", async (endpoint) => {
  // Arrange
  const { user, queryClient } = openPage();
  await screen.findByRole("button", { name: "Copy workspace ID workspace-alpha" });
  server.use(http.get(`/api/v1/admin/${endpoint}`, () => HttpResponse.json({}, { status: 403 })));
  // Act
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  await screen.findByText(/Not allowed/);
  // Assert
  await waitFor(() =>
    expect(
      queryClient.getQueriesData({ queryKey: ADMIN_KEY }).every(([, data]) => data === undefined),
    ).toBe(true),
  );
});

test("a refusal refreshes administrator identity", async () => {
  // Arrange
  const { user, onForbidden } = openPage();
  await screen.findByRole("button", { name: "Copy workspace ID workspace-alpha" });
  server.use(http.get("/api/v1/admin/metrics", () => HttpResponse.json({}, { status: 403 })));
  // Act
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  // Assert
  await waitFor(() => expect(onForbidden).toHaveBeenCalled());
});

test.for(["metrics", "jobs"])("a %s refusal stops requests to both endpoints", async (endpoint) => {
  // Arrange
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const requests: string[] = [];
  serve();
  server.use(
    http.get("/api/v1/admin/metrics", () => {
      requests.push("metrics");
      return endpoint === "metrics"
        ? HttpResponse.json({}, { status: 403 })
        : HttpResponse.json(metrics);
    }),
    http.get("/api/v1/admin/jobs", () => {
      requests.push("jobs");
      return endpoint === "jobs"
        ? HttpResponse.json({}, { status: 403 })
        : HttpResponse.json(page([job()]));
    }),
  );
  renderWithProviders(<AdminPage filters={{}} onFilters={() => {}} onForbidden={() => {}} />);
  await screen.findByText(/Not allowed/);
  await act(() => vi.advanceTimersByTimeAsync(100));
  const before = [...requests];
  // Act
  await act(() => vi.advanceTimersByTimeAsync(MONITOR_INTERVAL_MS * 3));
  // Assert
  expect(requests).toEqual(before);
});

test("a late successful response cannot restore data after a refusal", async () => {
  // Arrange
  const { user } = openPage();
  await screen.findByRole("button", { name: "Copy workspace ID workspace-alpha" });
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
  expect(
    screen.queryByRole("button", { name: "Copy workspace ID workspace-alpha" }),
  ).not.toBeInTheDocument();
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
  await screen.findByRole("button", { name: "Copy workspace ID workspace-alpha" });
  // Act
  await user.click(screen.getByRole("button", { name: "Load more" }));
  await screen.findByRole("button", { name: "Copy workspace ID workspace-beta" });
  // Assert
  expect(cursors).toEqual([null, "opaque-next"]);
});

test("shows running time", async () => {
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
});

test("a transient failure retains the dated snapshot and offers retry", async () => {
  // Arrange
  const { user } = openPage();
  await screen.findByRole("button", { name: "Copy workspace ID workspace-alpha" });
  server.use(http.get("/api/v1/admin/jobs", () => HttpResponse.json({}, { status: 500 })));
  // Act
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  await screen.findByText(/Jobs could not/);
  // Assert
  expect(screen.getByRole("button", { name: "Copy workspace ID workspace-alpha" })).toBeVisible();
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

test("polling fetches fresh metrics", async () => {
  // Arrange
  vi.useFakeTimers({ shouldAdvanceTime: true });
  openPage();
  await screen.findByRole("button", { name: "Copy workspace ID workspace-alpha" });
  server.use(
    http.get("/api/v1/admin/metrics", () =>
      HttpResponse.json({
        ...metrics,
        jobs: [{ ...metrics.jobs[0], queued: 7 }],
      }),
    ),
  );
  // Act
  await act(() => vi.advanceTimersByTimeAsync(MONITOR_INTERVAL_MS));
  // Assert
  await waitFor(() => expect(countValue("Queued")).toHaveTextContent("7"));
});

test("jobs polling automatically displays changed job data", async () => {
  // Arrange
  vi.useFakeTimers({ shouldAdvanceTime: true });
  openPage();
  await screen.findByText("Waiting: Unknown · Attempts: 0");
  server.use(
    http.get("/api/v1/admin/jobs", () =>
      HttpResponse.json(
        page([job({ status: "running", running_seconds: 65, attempts_started: 2 })]),
      ),
    ),
  );
  // Act
  await act(() => vi.advanceTimersByTimeAsync(MONITOR_INTERVAL_MS));
  // Assert
  expect(await screen.findByText("Running: 1m 5s · Attempts: 2")).toBeVisible();
});

test.for([
  [0, null, "None queued"],
  [1, null, "Unknown"],
  [1, 0, "0m 0s"],
  [2, 65, "1m 5s"],
] as const)("oldest wait with %s queued and %s seconds is %s", async ([queued, wait, expected]) => {
  // Arrange
  openPage();
  server.use(
    http.get("/api/v1/admin/metrics", () =>
      HttpResponse.json({
        ...metrics,
        jobs: [{ ...metrics.jobs[0], queued, oldest_queue_wait_seconds: wait }],
      }),
    ),
  );
  // Act
  await screen.findByText("Oldest known queue wait");
  // Assert
  expect(countValue("Oldest known queue wait")).toHaveTextContent(expected);
});

test("shows the count of unknown queue waits separately", async () => {
  // Arrange
  openPage();
  // Act
  await screen.findByText("Unknown queue waits");
  // Assert
  expect(countValue("Unknown queue waits")).toHaveTextContent("1");
});

test("a failed job with zero attempts has not started", async () => {
  // Arrange
  openPage();
  server.use(
    http.get("/api/v1/admin/jobs", () => HttpResponse.json(page([job({ status: "failed" })]))),
  );
  // Act
  const timing = await screen.findByText("Not started · Attempts: 0");
  // Assert
  expect(timing).toBeVisible();
});

test.for([0, 65, null])("a finished attempt renders its %s duration", async (value) => {
  // Arrange
  openPage();
  server.use(
    http.get("/api/v1/admin/jobs", () =>
      HttpResponse.json(
        page([
          job({
            status: "failed",
            attempts_started: 1,
            last_attempt_duration_seconds: value,
            queue_wait_seconds: 999,
          }),
        ]),
      ),
    ),
  );
  // Act
  await screen.findByRole("button", { name: "Copy workspace ID workspace-alpha" });
  // Assert
  expect(
    screen.getByText(
      `Last attempt: ${value === null ? "Unknown" : value === 0 ? "0m 0s" : "1m 5s"} · Attempts: 1`,
    ),
  ).toBeVisible();
});

test("copying a shortened job ID copies the full identifier", async () => {
  // Arrange
  const { user } = openPage();
  const id = "29dd39f7-c5c8-438b-9b4f-530839c8fc59";
  server.use(http.get("/api/v1/admin/jobs", () => HttpResponse.json(page([job({ job_id: id })]))));
  // Act
  await user.click(await screen.findByRole("button", { name: `Copy job ID ${id}` }));
  // Assert
  expect(await navigator.clipboard.readText()).toBe(id);
});

test("a refused job-ID copy offers the full ID for manual copying", async () => {
  // Arrange
  const { user } = openPage();
  vi.spyOn(navigator.clipboard, "writeText").mockRejectedValueOnce(new DOMException("Denied"));
  // Act
  await user.click(await screen.findByRole("button", { name: "Copy job ID job-1" }));
  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Copy this job ID manually: job-1");
});

test.for(["failed", "succeeded"] as const)("a %s job shows its finish time", async (status) => {
  // Arrange
  openPage();
  server.use(
    http.get("/api/v1/admin/jobs", () =>
      HttpResponse.json(page([job({ status, finished_at: STAMP })])),
    ),
  );
  // Act
  const finish = await screen.findByText(`Finished ${new Date(STAMP).toLocaleString()}`);
  // Assert
  expect(finish).toBeVisible();
});

test("a running job shows its start time", async () => {
  // Arrange
  openPage();
  server.use(
    http.get("/api/v1/admin/jobs", () =>
      HttpResponse.json(page([job({ status: "running", started_at: STAMP })])),
    ),
  );
  // Act
  const start = await screen.findByText(`Started ${new Date(STAMP).toLocaleString()}`);
  // Assert
  expect(start).toBeVisible();
});

test.for([
  [0, "0m 0s"],
  [65, "1m 5s"],
  [null, "Unknown"],
] as const)(
  "shows total elapsed and the %s queue wait before an attempt",
  async ([wait, expected]) => {
    // Arrange
    openPage();
    server.use(
      http.get("/api/v1/admin/jobs", () =>
        HttpResponse.json(
          page([
            job({
              status: "succeeded",
              attempts_started: 2,
              total_elapsed_seconds: 180,
              last_queue_wait_seconds: wait,
              last_attempt_duration_seconds: 25,
            }),
          ]),
        ),
      ),
    );
    // Act
    const timing = await screen.findByText(
      `Total elapsed: 3m 0s · Queue before attempt: ${expected}`,
    );
    // Assert
    expect(timing).toBeVisible();
  },
);

test("a metrics failure displays a warning", async () => {
  // Arrange
  openPage();
  server.use(http.get("/api/v1/admin/metrics", () => HttpResponse.json({}, { status: 500 })));
  // Act
  const warning = await screen.findByRole("alert");
  // Assert
  expect(warning).toHaveTextContent("Metrics could not be refreshed.");
});

test("retrying a failed next page keeps the cursor and existing jobs", async () => {
  // Arrange
  const { user } = openPage();
  const cursors: (string | null)[] = [];
  let failed = false;
  server.use(
    http.get("/api/v1/admin/jobs", ({ request }) => {
      const cursor = new URL(request.url).searchParams.get("cursor");
      cursors.push(cursor);
      if (!cursor) return HttpResponse.json(page([job()], "next"));
      if (!failed) {
        failed = true;
        return HttpResponse.json({}, { status: 500 });
      }
      return HttpResponse.json(page([job({ job_id: "job-2", workspace_id: "workspace-beta" })]));
    }),
  );
  await screen.findByRole("button", { name: "Copy workspace ID workspace-alpha" });
  await user.click(screen.getByRole("button", { name: "Load more" }));
  await screen.findByText(/Jobs could not/);
  // Act
  await user.click(screen.getByRole("button", { name: "Retry jobs" }));
  await screen.findByRole("button", { name: "Copy workspace ID workspace-beta" });
  // Assert
  expect(cursors).toEqual([null, "next", "next"]);
});

test("leaving monitoring discards snapshots before a later visit", async () => {
  // Arrange
  const { unmount, queryClient } = openPage();
  await screen.findByRole("button", { name: "Copy workspace ID workspace-alpha" });
  await screen.findByText(/Counts assembled/);
  // Act
  unmount();
  // Assert
  await waitFor(() => expect(queryClient.getQueriesData({ queryKey: ADMIN_KEY })).toEqual([]));
});
