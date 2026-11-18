import { screen, waitFor, within } from "@testing-library/react";
import { expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { errorBody, page } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { AccessRequests } from "./AccessRequests";

function accessRequest(changes: Partial<Schemas["RequestRead"]> = {}): Schemas["RequestRead"] {
  return {
    id: "request",
    requester_user_id: "requester",
    name: "Rita Recipient",
    email: "rita@example.test",
    status: "pending",
    ...changes,
  };
}

function serveRequests(requests: Schemas["RequestRead"][], pageSize = 100) {
  const decided: string[] = [];
  const decide = (id: string, status: Schemas["RequestRead"]["status"]) => {
    const decidedRequest = requests.find((item) => item.id === id);
    if (decidedRequest) decidedRequest.status = status;
    return accessRequest({ id, status });
  };
  server.use(
    http.get("/api/v1/shares/{share_id}/access-requests", ({ request, response }) => {
      const start = Number(new URL(request.url).searchParams.get("cursor") ?? 0);
      const end = start + pageSize;
      return response(200).json(
        page(requests.slice(start, end), end < requests.length ? String(end) : null),
      );
    }),
    http.post("/api/v1/share-access-requests/{request_id}/approve", ({ params, response }) => {
      decided.push(`approve ${params.request_id}`);
      return response(200).json(decide(params.request_id, "approved"));
    }),
    http.post("/api/v1/share-access-requests/{request_id}/decline", ({ params, response }) => {
      decided.push(`decline ${params.request_id}`);
      return response(200).json(decide(params.request_id, "declined"));
    }),
  );
  return decided;
}

test("each request shows who asked and what was decided", async () => {
  // Arrange
  serveRequests([
    accessRequest({ id: "pending" }),
    accessRequest({ id: "approved", name: "Ann Approved", status: "approved" }),
    accessRequest({ id: "declined", name: "Dan Declined", status: "declined" }),
  ]);

  // Act
  renderWithProviders(<AccessRequests shareId="share" />);

  // Assert
  expect(
    within(await screen.findByRole("list", { name: "Access requests" }))
      .getAllByRole("listitem")
      .map((item) => item.textContent),
  ).toEqual([
    "Rita Recipientrita@example.testDecline",
    "Ann Approvedrita@example.testApproved",
    "Dan Declinedrita@example.testDeclined",
  ]);
});

test("approving a request approves that request", async () => {
  // Arrange
  const decided = serveRequests([accessRequest({ id: "first" })]);
  const { user } = renderWithProviders(<AccessRequests shareId="share" />);

  // Act
  await user.click(await screen.findByRole("button", { name: "Approve" }));

  // Assert
  await waitFor(() => expect(decided).toEqual(["approve first"]));
});

test("an approved request reads Approved after the click", async () => {
  // Arrange
  serveRequests([accessRequest({ id: "first" })]);
  const { user } = renderWithProviders(<AccessRequests shareId="share" />);

  // Act
  await user.click(await screen.findByRole("button", { name: "Approve" }));

  // Assert
  expect(await screen.findByText("Approved")).toBeInTheDocument();
});

test("pending requests can only be declined once one is approved", async () => {
  // Arrange
  serveRequests([accessRequest({ id: "first" }), accessRequest({ id: "second" })]);
  const { user } = renderWithProviders(<AccessRequests shareId="share" />);

  // Act
  await user.click((await screen.findAllByRole("button", { name: "Approve" }))[0] as HTMLElement);

  // Assert
  await waitFor(() => expect(screen.queryByRole("button", { name: "Approve" })).toBeNull());
  expect(screen.getByRole("button", { name: "Decline" })).toBeInTheDocument();
});

test("a refused approval shows why", async () => {
  // Arrange
  serveRequests([accessRequest({ id: "first" })]);
  server.use(
    http.post("/api/v1/share-access-requests/{request_id}/approve", ({ response }) =>
      response(409).json(
        errorBody("SHARE_ALREADY_BOUND", "The share is already bound to another account"),
      ),
    ),
  );
  const { user } = renderWithProviders(<AccessRequests shareId="share" />);

  // Act
  await user.click(await screen.findByRole("button", { name: "Approve" }));

  // Assert
  expect(
    await screen.findByText("The share is already bound to another account"),
  ).toBeInTheDocument();
});

test("Show more loads the next page and disappears after the last", async () => {
  // Arrange
  serveRequests([accessRequest({ id: "first" }), accessRequest({ id: "second" })], 1);
  const { user } = renderWithProviders(<AccessRequests shareId="share" />);

  // Act
  await user.click(await screen.findByRole("button", { name: "Show more" }));

  // Assert
  await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
  expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
});

test("a request on the second page can be approved", async () => {
  // Arrange
  const decided = serveRequests(
    [accessRequest({ id: "first" }), accessRequest({ id: "second" })],
    1,
  );
  const { user } = renderWithProviders(<AccessRequests shareId="share" />);
  await user.click(await screen.findByRole("button", { name: "Show more" }));
  await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));

  // Act
  await user.click(screen.getAllByRole("button", { name: "Approve" })[1] as HTMLElement);

  // Assert
  await waitFor(() => expect(decided).toEqual(["approve second"]));
});

test("declining a request declines that request", async () => {
  // Arrange
  const decided = serveRequests([accessRequest({ id: "first" })]);
  const { user } = renderWithProviders(<AccessRequests shareId="share" />);

  // Act
  await user.click(await screen.findByRole("button", { name: "Decline" }));

  // Assert
  await waitFor(() => expect(decided).toEqual(["decline first"]));
});

test("someone who did not create the share is told so", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/shares/{share_id}/access-requests", ({ response }) =>
      response(403).json(errorBody("INSUFFICIENT_ROLE", "Forbidden")),
    ),
  );

  // Act
  renderWithProviders(<AccessRequests shareId="share" />);

  // Assert
  expect(
    await screen.findByText("Only the person who created this share can see its requests."),
  ).toBeInTheDocument();
});

test("a share that does not exist is told so", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/shares/{share_id}/access-requests", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "Not found")),
    ),
  );

  // Act
  renderWithProviders(<AccessRequests shareId="share" />);

  // Assert
  expect(await screen.findByText("This share does not exist.")).toBeInTheDocument();
});

test("a share nobody asked about says so", async () => {
  // Arrange
  serveRequests([]);

  // Act
  renderWithProviders(<AccessRequests shareId="share" />);

  // Assert
  expect(await screen.findByText("No requests yet")).toBeInTheDocument();
});
