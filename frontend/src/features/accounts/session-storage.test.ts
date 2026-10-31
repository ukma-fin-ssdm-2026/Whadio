import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { denySessionStorage } from "@/shared/testing/deny-storage";
import { clearSignedInUser, readSignedInUser, storeSignedInUser } from "./session-storage";

const USER = { id: "member", email: "member@example.com", name: "Demo Member" };

beforeEach(() => {
  sessionStorage.clear();
});

test("reads back the stored user", () => {
  // Arrange
  storeSignedInUser(USER);

  // Act
  const user = readSignedInUser();

  // Assert
  expect(user).toEqual(USER);
});

test("reads no user once cleared", () => {
  // Arrange
  storeSignedInUser(USER);

  // Act
  clearSignedInUser();

  // Assert
  expect(readSignedInUser()).toBeNull();
});

test.for([
  ["malformed JSON", "{"],
  ["a value of the wrong shape", JSON.stringify({ email: "member@example.com" })],
] as const)("ignores %s", ([, stored]) => {
  // Arrange
  sessionStorage.setItem("whadio-user", stored);

  // Act
  const user = readSignedInUser();

  // Assert
  expect(user).toBeNull();
});

describe("when storage is denied", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("reads no user", () => {
    // Arrange
    denySessionStorage();

    // Act
    const user = readSignedInUser();

    // Assert
    expect(user).toBeNull();
  });

  test("storing a user does not throw", () => {
    // Arrange
    denySessionStorage();

    // Act
    const store = () => storeSignedInUser(USER);

    // Assert
    expect(store).not.toThrow();
  });

  test("clearing the user does not throw", () => {
    // Arrange
    denySessionStorage();

    // Act
    const clear = () => clearSignedInUser();

    // Assert
    expect(clear).not.toThrow();
  });
});
