import { describe, expect, test } from "vitest";
import { normalizeApiOrigin } from "./client";

describe("normalizeApiOrigin", () => {
  test("removes a trailing slash", () => {
    // Act
    const origin = normalizeApiOrigin("https://api.example.com/");

    // Assert
    expect(origin).toBe("https://api.example.com");
  });

  test("removes several trailing slashes", () => {
    // Act
    const origin = normalizeApiOrigin("https://api.example.com///");

    // Assert
    expect(origin).toBe("https://api.example.com");
  });

  test("keeps a configured path prefix", () => {
    // Act
    const origin = normalizeApiOrigin("https://example.com/whadio/");

    // Assert
    expect(origin).toBe("https://example.com/whadio");
  });

  test.for(["", undefined])("treats %s as the page's own origin", (configured) => {
    // Act
    const origin = normalizeApiOrigin(configured);

    // Assert
    expect(origin).toBe("");
  });
});
