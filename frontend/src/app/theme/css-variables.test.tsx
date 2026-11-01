import { CssBaseline, ThemeProvider } from "@mui/material";
import type { PaletteOptions } from "@mui/material/styles";
import { render } from "@testing-library/react";
import { expect, test } from "vitest";
import stylesheet from "@/styles.css?raw";
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

const referencedVariables = () =>
  [...stylesheet.matchAll(/var\((--mui-[\w-]+)/g)].map(([, name = ""]) => name);

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

test("styles.css is read as text with MUI variable references in it", () => {
  // Arrange
  const expected = "--mui-palette-divider";

  // Act
  const referenced = referencedVariables();

  // Assert
  expect(referenced).toContain(expected);
});

test("every MUI variable styles.css references is defined", () => {
  // Arrange
  const referenced = referencedVariables();

  // Act
  const { defaults } = renderEmittedVariables();
  const missing = referenced.filter((name) => !(name in defaults));

  // Assert
  expect(missing).toEqual([]);
});
