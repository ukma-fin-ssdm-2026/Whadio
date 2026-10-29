import { getContrastRatio, type Palette } from "@mui/material/styles";
import { expect, test } from "vitest";
import { theme } from "./index";

const WCAG_AA_TEXT = 4.5;

const typeScale = [
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "subtitle1",
  "subtitle2",
  "body1",
  "body2",
  "caption",
  "overline",
  "button",
] as const;

const textPairs: [string, (palette: Palette) => [string, string]][] = [
  ["primary text on the page", (p) => [p.text.primary, p.background.default]],
  ["secondary text on the page", (p) => [p.text.secondary, p.background.default]],
  ["secondary text on a subtle panel", (p) => [p.text.secondary, p.background.subtle]],
  ["primary colour on the page", (p) => [p.primary.main, p.background.default]],
  ["button label on the primary colour", (p) => [p.primary.contrastText, p.primary.main]],
  ["tint text on the tint", (p) => [p.tint.contrastText, p.tint.main]],
  ["error text on paper", (p) => [p.error.main, p.background.paper]],
];

const contrastCases = (["light", "dark"] as const).flatMap((scheme) =>
  textPairs.map(([name, pick]) => ({ scheme, name, pick })),
);

test("defines a light and a dark colour scheme", () => {
  // Arrange
  const expected = ["dark", "light"];

  // Act
  const schemes = Object.keys(theme.colorSchemes).sort();

  // Assert
  expect(schemes).toEqual(expected);
});

test("follows the operating system's colour scheme", () => {
  // Arrange
  const expected = "media";

  // Act
  const selector = theme.colorSchemeSelector;

  // Assert
  expect(selector).toBe(expected);
});

test.each(contrastCases)("$scheme scheme: $name meets WCAG AA contrast", ({ scheme, pick }) => {
  // Arrange
  const palette = theme.colorSchemes[scheme]?.palette;

  // Act
  const ratio = palette ? getContrastRatio(...pick(palette)) : 0;

  // Assert
  expect(ratio).toBeGreaterThanOrEqual(WCAG_AA_TEXT);
});

test("h1 is the only variant larger than h2", () => {
  // Arrange
  const h2Size = Number.parseFloat(String(theme.typography.h2.fontSize));

  // Act
  const larger = typeScale.filter(
    (variant) => Number.parseFloat(String(theme.typography[variant].fontSize)) > h2Size,
  );

  // Assert
  expect(larger).toEqual(["h1"]);
});

test("button labels keep their case", () => {
  // Arrange
  const { button } = theme.typography;

  // Act
  const transform = button.textTransform;

  // Assert
  expect(transform).toBe("none");
});
