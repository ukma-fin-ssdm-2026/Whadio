import { act, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { McpKeyPanel } from "./McpKeyPanel";

type McpKey = Schemas["McpKeyRead"];

const ACTIVE: McpKey = {
  id: "0f6c1d2e-8a4b-4c5d-9e0f-1a2b3c4d5e6f",
  created_at: "2026-10-25T10:00:00Z",
  expires_at: null,
  revoked_at: null,
  is_active: true,
};

const REVOKED: McpKey = {
  ...ACTIVE,
  id: "9e0f1a2b-8a4b-4c5d-9e0f-1a2b3c4d5e6f",
  revoked_at: "2026-10-26T10:00:00Z",
  is_active: false,
};

const SECRET = "whadio_mcp_secret";

const serverError = () =>
  HttpResponse.json(
    {
      error: {
        code: "INTERNAL_ERROR",
        message: "Unexpected server error",
        details: [],
        request_id: "req_1",
      },
    },
    { status: 500 },
  );

function failListing() {
  server.use(
    http.get("/api/v1/users/me/mcp-keys", ({ response }) => response.untyped(serverError())),
  );
}

type Traffic = { created: unknown[]; revoked: string[] };

function serveKeys(initial: McpKey[]): Traffic {
  let keys = initial;
  const traffic: Traffic = { created: [], revoked: [] };
  server.use(
    http.get("/api/v1/users/me/mcp-keys", ({ response }) =>
      response(200).json({
        items: keys,
        pagination: { limit: 100, next_cursor: null, has_more: false },
      }),
    ),
    http.post("/api/v1/users/me/mcp-keys", async ({ request, response }) => {
      traffic.created.push(await request.json());
      return response(201).json({ ...ACTIVE, id: "1a2b3c4d-new", secret: SECRET });
    }),
    http.delete("/api/v1/users/me/mcp-keys/{key_id}", ({ params, response }) => {
      traffic.revoked.push(params.key_id);
      keys = keys.map((key) =>
        key.id === params.key_id
          ? { ...key, is_active: false, revoked_at: ACTIVE.created_at }
          : key,
      );
      return response(204).empty();
    }),
  );
  return traffic;
}

async function renderPanel(keys: McpKey[] = [ACTIVE]) {
  const traffic = serveKeys(keys);
  const rendered = renderWithProviders(<McpKeyPanel />);
  const [first] = keys;
  await screen.findByText(first ? `Key ${first.id.slice(0, 8)}` : "No assistant keys yet");
  return { ...rendered, traffic };
}

async function createKey(expiry?: string) {
  const panel = await renderPanel();
  if (expiry) {
    await panel.user.click(screen.getByRole("combobox", { name: "Expires" }));
    await panel.user.click(screen.getByRole("option", { name: expiry }));
  }
  await panel.user.click(screen.getByRole("button", { name: "Create key" }));
  await screen.findByRole("dialog", { name: "Save your MCP key" });
  return panel;
}

async function askToRevoke() {
  const panel = await renderPanel();
  await panel.user.click(screen.getByRole("button", { name: "Revoke key" }));
  return panel;
}

describe("key list", () => {
  test("shows each key's status", async () => {
    // Act
    await renderPanel([ACTIVE, REVOKED]);

    // Assert
    expect(screen.getAllByText(/^(Active|Revoked)$/).map((chip) => chip.textContent)).toEqual([
      "Active",
      "Revoked",
    ]);
  });

  test("offers no revoke for a revoked key", async () => {
    // Act
    await renderPanel([REVOKED]);

    // Assert
    expect(screen.queryByRole("button", { name: "Revoke key" })).not.toBeInTheDocument();
  });

  test("says when there are no keys", async () => {
    // Act
    await renderPanel([]);

    // Assert
    expect(screen.getByText("No assistant keys yet")).toBeInTheDocument();
  });

  test("shows why the keys could not load", async () => {
    // Arrange
    failListing();

    // Act
    renderWithProviders(<McpKeyPanel />);

    // Assert
    expect(await screen.findByRole("alert")).toHaveTextContent("Unexpected server error");
  });

  test("does not claim there are no keys when they could not load", async () => {
    // Arrange
    failListing();

    // Act
    renderWithProviders(<McpKeyPanel />);
    await screen.findByRole("alert");

    // Assert
    expect(screen.queryByText("No assistant keys yet")).not.toBeInTheDocument();
  });

  test("keeps the listed keys when refreshing them fails", async () => {
    // Arrange
    const { queryClient } = await renderPanel();
    failListing();

    // Act
    await act(() => queryClient.invalidateQueries());
    await screen.findByRole("alert");

    // Assert
    expect(screen.getByText(`Key ${ACTIVE.id.slice(0, 8)}`)).toBeInTheDocument();
  });
});

describe("creating a key", () => {
  test("defaults to a 30-day lifetime", async () => {
    // Act
    const { traffic } = await createKey();

    // Assert
    expect(traffic.created).toEqual([{ expires_in_days: 30 }]);
  });

  test("that never expires sends a null lifetime", async () => {
    // Act
    const { traffic } = await createKey("Never");

    // Assert
    expect(traffic.created).toEqual([{ expires_in_days: null }]);
  });

  test("shows the secret once in a dialog", async () => {
    // Act
    await createKey();

    // Assert
    expect(screen.getByLabelText("MCP key secret")).toHaveValue(SECRET);
  });

  test("copying the secret confirms it was copied", async () => {
    // Arrange
    const { user } = await createKey();

    // Act
    await user.click(screen.getByRole("button", { name: "Copy key" }));

    // Assert
    expect(await screen.findByRole("alert")).toHaveTextContent("Copied");
  });

  test("closing the dialog discards the secret", async () => {
    // Arrange
    const { user } = await createKey();

    // Act
    await user.click(screen.getByRole("button", { name: "Done" }));

    // Assert
    await waitFor(() => expect(screen.queryByLabelText("MCP key secret")).not.toBeInTheDocument());
  });
});

describe("revoking a key", () => {
  test("asks for confirmation first", async () => {
    // Act
    await askToRevoke();

    // Assert
    expect(screen.getByRole("dialog", { name: "Revoke this key?" })).toBeInTheDocument();
  });

  test("sends nothing before it is confirmed", async () => {
    // Act
    const { traffic } = await askToRevoke();

    // Assert
    expect(traffic.revoked).toEqual([]);
  });

  test("sends nothing when cancelled", async () => {
    // Arrange
    const { traffic, user } = await askToRevoke();

    // Act
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    // Assert
    expect(traffic.revoked).toEqual([]);
  });

  test("once confirmed, revokes the key", async () => {
    // Arrange
    const { traffic, user } = await askToRevoke();

    // Act
    await user.click(screen.getByRole("button", { name: "Revoke" }));

    // Assert
    await waitFor(() => expect(traffic.revoked).toEqual([ACTIVE.id]));
  });

  test("once confirmed, shows the refreshed status", async () => {
    // Arrange
    const { user } = await askToRevoke();
    const row = screen.getByText(`Key ${ACTIVE.id.slice(0, 8)}`).closest("li");

    // Act
    await user.click(screen.getByRole("button", { name: "Revoke" }));

    // Assert
    expect(await within(row ?? document.body).findByText("Revoked")).toBeInTheDocument();
  });
});
