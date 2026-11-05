import { expect, test } from "vitest";
import { speakerInitials } from "./segments";

test("a named speaker shows the initials of their first and last names", () => {
  // Act
  const initials = speakerInitials("Olena Maria Bondar");

  // Assert
  expect(initials).toBe("OB");
});

test("a numbered speaker keeps the whole number", () => {
  // Act
  const initials = speakerInitials("Speaker 12");

  // Assert
  expect(initials).toBe("S12");
});

test("a one-word name shows its first letter", () => {
  // Act
  const initials = speakerInitials("Olena");

  // Assert
  expect(initials).toBe("O");
});

test("initials are capital letters", () => {
  // Act
  const initials = speakerInitials("олена бондар");

  // Assert
  expect(initials).toBe("ОБ");
});

test("an initial outside the basic plane stays whole", () => {
  // Act
  const initials = speakerInitials("𝒜da Lovelace");

  // Assert
  expect(initials).toBe("𝒜L");
});
