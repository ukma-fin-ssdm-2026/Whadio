import { describe, expect, test } from "vitest";
import { serializeBody } from "./body";

const fieldsOf = (body: FormData | string) =>
  body instanceof FormData
    ? [...body.entries()].map(([key, value]) => [key, typeof value === "string" ? value : "<blob>"])
    : body;

describe("serializeBody", () => {
  test("sends a body with a Blob field as form data", () => {
    // Arrange
    const file = new Blob(["RIFF"], { type: "audio/wav" });

    // Act
    const body = serializeBody({ file, name: "Standup" });

    // Assert
    expect(body).toBeInstanceOf(FormData);
  });

  test("puts the Blob and the text fields into the form", () => {
    // Arrange
    const audio = new Blob(["RIFF"], { type: "audio/wav" });

    // Act
    const body = serializeBody({ audio, speaker_events: "[]" });

    // Assert
    expect(fieldsOf(body)).toEqual([
      ["audio", "<blob>"],
      ["speaker_events", "[]"],
    ]);
  });

  test("keeps the Blob's contents in its part", async () => {
    // Arrange
    const file = new Blob(["RIFF"], { type: "audio/wav" });

    // Act
    const body = serializeBody({ file });

    // Assert
    const part = body instanceof FormData ? body.get("file") : null;
    await expect(part instanceof Blob ? part.text() : part).resolves.toBe("RIFF");
  });

  test("leaves undefined and null fields out of the form", () => {
    // Arrange
    const file = new Blob(["RIFF"]);

    // Act
    const body = serializeBody({ file, name: undefined, folder_id: null });

    // Assert
    expect(fieldsOf(body)).toEqual([["file", "<blob>"]]);
  });

  test("writes a field that is not text as JSON", () => {
    // Arrange
    const file = new Blob(["RIFF"]);

    // Act
    const body = serializeBody({ file, seq: 3 });

    // Assert
    expect(fieldsOf(body)).toEqual([
      ["file", "<blob>"],
      ["seq", "3"],
    ]);
  });

  test("sends a body without a Blob as JSON", () => {
    // Act
    const body = serializeBody({ email: "member@example.com", kind: "browser" });

    // Assert
    expect(body).toBe('{"email":"member@example.com","kind":"browser"}');
  });

  test("passes a FormData body through", () => {
    // Arrange
    const form = new FormData();

    // Act
    const body = serializeBody(form);

    // Assert
    expect(body).toBe(form);
  });
});
