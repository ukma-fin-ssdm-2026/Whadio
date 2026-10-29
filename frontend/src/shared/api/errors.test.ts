import { describe, expect, test } from "vitest";
import { ApiError, UNEXPECTED_RESPONSE } from "./errors";

const envelope = (code: string, details?: unknown[]) => ({
  error: { code, message: "Not transcribed yet", details, request_id: "req_1" },
});

describe("ApiError.from", () => {
  test("reads the code, message, details and request ID of an error envelope", () => {
    // Arrange
    const details = [{ field: "revision_id", message: "Unknown revision" }];

    // Act
    const error = ApiError.from(
      new Response(null, { status: 409 }),
      envelope("NOT_TRANSCRIBED", details),
    );

    // Assert
    expect(error).toMatchObject({
      status: 409,
      code: "NOT_TRANSCRIBED",
      message: "Not transcribed yet",
      details,
      requestId: "req_1",
    });
  });

  test("gives an envelope without details an empty list", () => {
    // Act
    const error = ApiError.from(new Response(null, { status: 409 }), envelope("NOT_TRANSCRIBED"));

    // Assert
    expect(error.details).toEqual([]);
  });

  test("keeps the status of an unauthenticated request", () => {
    // Act
    const error = ApiError.from(new Response(null, { status: 401 }), envelope("UNAUTHENTICATED"));

    // Assert
    expect(error).toMatchObject({ status: 401, code: "UNAUTHENTICATED" });
  });

  test("describes a proxy's HTML page by its status", () => {
    // Act
    const error = ApiError.from(new Response(null, { status: 502 }), "<html>Bad Gateway</html>");

    // Assert
    expect(error).toMatchObject({
      status: 502,
      code: UNEXPECTED_RESPONSE,
      message: "Request failed (502)",
    });
  });

  test("treats JSON that is not the envelope as unexpected", () => {
    // Act
    const error = ApiError.from(new Response(null, { status: 422 }), { detail: [] });

    // Assert
    expect(error.code).toBe(UNEXPECTED_RESPONSE);
  });

  test("treats an envelope with an unknown code as unexpected", () => {
    // Act
    const error = ApiError.from(new Response(null, { status: 409 }), envelope("SOMETHING_NEW"));

    // Assert
    expect(error.code).toBe(UNEXPECTED_RESPONSE);
  });
});
