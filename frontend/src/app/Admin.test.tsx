import { render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { expect, test } from "vitest";
import { App } from "@/app/App";
import { serveApi, stubViewportWidth } from "@/app/testing";
import { job, serve } from "@/features/admin/testing";
import { errorBody, page } from "@/shared/testing/fixtures";
import { server } from "@/shared/testing/server";

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

test("a fresh URL restores both filters", async () => {
  // Act
  await openApp(true, "/admin?job_type=notes&status=failed");
  await screen.findByText("Workspace: workspace-alpha");
  // Assert
  expect([
    screen.getByRole("combobox", { name: "Job type" }).textContent,
    screen.getByRole("combobox", { name: "State" }).textContent,
  ]).toEqual(["Notes", "Failed"]);
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

test.for([
  ["Job type", "Transcription", "job_type", "transcription", "status", "failed"],
  ["State", "Running", "status", "running", "job_type", "notes"],
] as const)(
  "changing %s preserves the other filter in the request and URL",
  async ([label, option, key, value, otherKey, otherValue]) => {
    // Arrange
    const requests: URL[] = [];
    await openApp(true, "/admin?job_type=notes&status=failed");
    server.use(
      http.get("/api/v1/admin/jobs", ({ request }) => {
        requests.push(new URL(request.url));
        return HttpResponse.json(page([job()], "next"));
      }),
    );
    await screen.findByText("Workspace: workspace-alpha");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(requests.at(-1)?.searchParams.get("cursor")).toBe("next"));
    // Act
    await user.click(screen.getByRole("combobox", { name: label }));
    await user.click(screen.getByRole("option", { name: option }));
    // Assert
    await waitFor(() =>
      expect({
        request: Object.fromEntries(requests.at(-1)?.searchParams ?? []),
        url: Object.fromEntries(new URL(window.location.href).searchParams),
      }).toEqual({
        request: {
          limit: "25",
          [key]: value,
          [otherKey]: otherValue,
        },
        url: { [key]: value, [otherKey]: otherValue },
      }),
    );
  },
);
