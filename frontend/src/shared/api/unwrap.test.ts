import { describe, expect, test } from "vitest";
import { ApiError, NETWORK_ERROR } from "./errors";
import { expectNoContent, unwrap } from "./unwrap";

const NOT_FOUND = {
  error: { code: "NOT_FOUND", message: "No such meeting", request_id: "req_1" },
};

const success = <T>(data: T) =>
  Promise.resolve({ data, response: new Response(null, { status: 200 }) });

const failure = (status: number, error: unknown) =>
  Promise.resolve({ error, response: new Response(null, { status }) });

describe("unwrap", () => {
  test("returns the data of a successful response", async () => {
    // Act
    const data = await unwrap(success({ id: "meeting" }));

    // Assert
    expect(data).toEqual({ id: "meeting" });
  });

  test("throws the error response as an ApiError", async () => {
    // Act
    const request = unwrap(failure(404, NOT_FOUND));

    // Assert
    await expect(request).rejects.toMatchObject({ status: 404, code: "NOT_FOUND" });
  });

  test("throws when a successful response has no body", async () => {
    // Act
    const request = unwrap(Promise.resolve({ response: new Response(null, { status: 200 }) }));

    // Assert
    await expect(request).rejects.toBeInstanceOf(ApiError);
  });

  test("throws a network ApiError when the request never gets a response", async () => {
    // Act
    const request = unwrap(Promise.reject(new TypeError("Failed to fetch")));

    // Assert
    await expect(request).rejects.toMatchObject({ status: 0, code: NETWORK_ERROR });
  });
});

describe("expectNoContent", () => {
  test("resolves on 204 No Content", async () => {
    // Act
    const request = expectNoContent(
      Promise.resolve({ response: new Response(null, { status: 204 }) }),
    );

    // Assert
    await expect(request).resolves.toBeUndefined();
  });

  test("throws the error response as an ApiError", async () => {
    // Act
    const request = expectNoContent(failure(404, NOT_FOUND));

    // Assert
    await expect(request).rejects.toMatchObject({ status: 404, code: "NOT_FOUND" });
  });
});
