import { expect, test } from "vitest";
import { workspaceSummary } from "@/shared/testing/fixtures";
import { mapWorkspace } from "./model";

test("a workspace takes its role and member count from the summary", () => {
  // Arrange
  const summary = workspaceSummary({ id: "alpha", name: "Alpha", my_role: "moderator" });

  // Act
  const workspace = mapWorkspace(summary);

  // Assert
  expect(workspace).toEqual({ id: "alpha", name: "Alpha", role: "Moderator", members: 2 });
});
