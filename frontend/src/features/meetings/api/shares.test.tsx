import { expect, test } from "vitest";
import { meetingQueries } from "./meetings";
import { shareQueries } from "./shares";

test("a meeting's shares sit under its detail key", () => {
  // Act
  const key = shareQueries.list("meeting").queryKey;

  // Assert
  expect(key.slice(0, 3)).toEqual(meetingQueries.detail("meeting").queryKey);
});
