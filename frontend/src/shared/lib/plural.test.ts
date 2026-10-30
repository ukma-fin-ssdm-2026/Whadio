import { expect, test } from "vitest";
import { countOf } from "./plural";

test.for([
  [0, "0 members"],
  [1, "1 member"],
  [2, "2 members"],
] as const)("%d reads as %s", ([count, label]) => {
  // Act
  const text = countOf(count, "member");

  // Assert
  expect(text).toBe(label);
});
