import { CssBaseline, ThemeProvider } from "@mui/material";
import type { PaletteOptions } from "@mui/material/styles";
import { render } from "@testing-library/react";
import { expect, test } from "vitest";
import { theme } from "./index";
import { darkPalette, lightPalette } from "./palette";

const DARK_RULE = /@media \(prefers-color-scheme: dark\)\{:root\{[^}]*\}\}/g;
const VARIABLE_DECLARATION = /(--mui-[\w-]+):([^;}]+)/g;

const colourVariables = (palette: PaletteOptions) => ({
  "--mui-palette-background-default": palette.background?.default,
  "--mui-palette-background-paper": palette.background?.paper,
  "--mui-palette-background-subtle": palette.background?.subtle,
  "--mui-palette-text-primary": palette.text?.primary,
  "--mui-palette-text-secondary": palette.text?.secondary,
  "--mui-palette-tint-main": palette.tint?.main,
  "--mui-palette-divider": palette.divider,
});

// sx values are plain strings, so nothing else would notice a variable that doesn't exist.
const styleSources = import.meta.glob<string>(
  ["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}", "!/src/**/*.gen.ts"],
  { query: "?raw", import: "default", eager: true },
);

const referencedVariables = (text: string) =>
  [...text.matchAll(/var\((--mui-[\w-]+)/g)].map(([, name = ""]) => name);

const declaredIn = (css: string) =>
  Object.fromEntries(
    [...css.matchAll(VARIABLE_DECLARATION)].map(([, name = "", value = ""]): [string, string] => [
      name,
      value,
    ]),
  );

// jsdom never applies a media query, so the rules are read as the text Emotion leaves in its
// <style> nodes, which it does only outside production.
const renderEmittedVariables = () => {
  render(
    <ThemeProvider theme={theme}>
      <CssBaseline enableColorScheme />
    </ThemeProvider>,
  );
  const css = Array.from(
    document.querySelectorAll("style[data-emotion]"),
    (style) => style.textContent,
  ).join("");
  return {
    css,
    defaults: declaredIn(css.replace(DARK_RULE, "")),
    dark: declaredIn(css.match(DARK_RULE)?.join("") ?? ""),
  };
};

test("the default scheme defines the light palette's colours", () => {
  // Arrange
  const expected = colourVariables(lightPalette);

  // Act
  const { defaults } = renderEmittedVariables();

  // Assert
  expect(defaults).toMatchObject(expected);
});

test("the prefers-color-scheme dark rule defines the dark palette's colours", () => {
  // Arrange
  const expected = colourVariables(darkPalette);

  // Act
  const { dark } = renderEmittedVariables();

  // Assert
  expect(dark).toMatchObject(expected);
});

test("the dark rule changes every palette colour from its default", () => {
  // Arrange
  const names = Object.keys(colourVariables(lightPalette));

  // Act
  const { defaults, dark } = renderEmittedVariables();
  const unchanged = names.filter((name) => defaults[name] === dark[name]);

  // Assert
  expect(unchanged).toEqual([]);
});

test("the app's sources are read as text with MUI variable references in them", () => {
  // Arrange
  const expected = "--mui-palette-error-mainChannel";

  // Act
  const referenced = Object.values(styleSources).flatMap(referencedVariables);

  // Assert
  expect(referenced).toContain(expected);
});

test("every MUI variable the app's sources and the baseline reference is defined", () => {
  // Arrange
  const sources = Object.values(styleSources).flatMap(referencedVariables);

  // Act
  const { css, defaults } = renderEmittedVariables();
  const referenced = [...sources, ...referencedVariables(css)];
  const missing = referenced.filter((name) => !(name in defaults));

  // Assert
  expect(missing).toEqual([]);
});

test("the body paints the primary tint over the page colour", () => {
  // Arrange
  const tint =
    /body\{[^}]*background-image:linear-gradient\(135deg, rgb\(var\(--mui-palette-primary-mainChannel\) \/ 7%\)/;

  // Act
  const { css } = renderEmittedVariables();

  // Assert
  expect(css).toMatch(tint);
});

test("the body keeps its minimum width", () => {
  // Arrange
  const minimum = /body\{[^}]*min-width:320px/;

  // Act
  const { css } = renderEmittedVariables();

  // Assert
  expect(css).toMatch(minimum);
});
