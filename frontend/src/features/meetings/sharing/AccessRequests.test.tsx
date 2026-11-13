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

function serveRequests(requests: Schemas["RequestRead"][]) {
  const decided: string[] = [];
  server.use(
    http.get("/api/v1/shares/{share_id}/access-requests", ({ response }) =>
      response(200).json(page(requests)),
    ),
    http.post("/api/v1/share-access-requests/{request_id}/approve", ({ params, response }) => {
      decided.push(`approve ${params.request_id}`);
      return response(200).json(accessRequest({ id: params.request_id, status: "approved" }));
    }),
    http.post("/api/v1/share-access-requests/{request_id}/decline", ({ params, response }) => {
      decided.push(`decline ${params.request_id}`);
      return response(200).json(accessRequest({ id: params.request_id, status: "declined" }));
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
    "Rita Recipientrita@example.testDeclineApprove",
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

test("a share nobody asked about says so", async () => {
  // Arrange
  serveRequests([]);

  // Act
  renderWithProviders(<AccessRequests shareId="share" />);

  // Assert
  expect(await screen.findByText("No requests yet")).toBeInTheDocument();
});
