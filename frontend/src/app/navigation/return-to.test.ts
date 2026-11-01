import { expect, test } from "vitest";
import { returnSearch, safeReturnPath } from "./return-to";

test.for([
  ["nothing", undefined],
  ["an empty value", ""],
  ["an absolute URL", "https://evil.example/meetings"],
  ["a protocol-relative URL", "//evil.example/meetings"],
  ["a backslash after the slash", "/\\evil.example"],
  ["two backslashes", "\\\\evil.example"],
  ["a tab inside the slashes", "/\t/evil.example"],
  ["a newline inside the slashes", "/\n/evil.example"],
  ["a script URL", "javascript:alert(1)"],
  ["a script URL behind a space", " javascript:alert(1)"],
  ["a data URL", "data:text/html,<script>alert(1)</script>"],
  ["a relative path", "meetings/meeting"],
] as const)("%s falls back to Home", ([, target]) => {
  // Act
  const path = safeReturnPath(target);

  // Assert
  expect(path).toBe("/");
});

test("a path of this app survives with its search", () => {
  // Act
  const path = safeReturnPath("/meetings/meeting?revision_id=original");

  // Assert
  expect(path).toBe("/meetings/meeting?revision_id=original");
});

test("a target loses its hash", () => {
  // Act
  const path = safeReturnPath("/meetings/meeting#token=secret");

  // Assert
  expect(path).toBe("/meetings/meeting");
});

test("the way back from Home is no way back at all", () => {
  // Act
  const search = returnSearch({ pathname: "/", searchStr: "" });

  // Assert
  expect(search).toEqual({});
});

test("the way back keeps the path and search", () => {
  // Act
  const search = returnSearch({ pathname: "/meetings/meeting", searchStr: "?revision_id=a" });

  // Assert
  expect(search).toEqual({ redirect: "/meetings/meeting?revision_id=a" });
});
