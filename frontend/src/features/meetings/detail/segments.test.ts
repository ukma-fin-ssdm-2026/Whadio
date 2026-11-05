import { expect, test } from "vitest";
import { speakerInitials } from "./segments";

test.for([
  ["a named speaker shows the initials of their first and last names", "Olena Maria Bondar", "OB"],
  ["a numbered speaker keeps the whole number", "Speaker 12", "S12"],
  ["a one-word name shows its first letter", "Olena", "O"],
  ["initials are capital letters", "олена бондар", "ОБ"],
  ["an initial outside the basic plane stays whole", "𝒜da Lovelace", "𝒜L"],
] as const)("%s", ([, name, expected]) => {
  // Act
  const initials = speakerInitials(name);

  // Assert
  expect(initials).toBe(expected);
});
