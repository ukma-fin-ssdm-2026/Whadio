import { CssBaseline, ThemeProvider } from "@mui/material";
import type { PaletteOptions } from "@mui/material/styles";
import { render } from "@testing-library/react";
import ts from "typescript";
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

// sx values are plain strings, so nothing else would notice a variable or a palette token that
// doesn't exist.
const styleSources = import.meta.glob<string>(
  ["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}", "!/src/**/*.gen.ts"],
  { query: "?raw", import: "default", eager: true },
);

const referencedVariables = (text: string) =>
  [...text.matchAll(/var\((--mui-[\w-]+)/g)].map(([, name = ""]) => name);

const PALETTE_PROPS = new Set(
  Object.entries(theme.unstable_sxConfig ?? {}).flatMap(([prop, { themeKey }]) =>
    themeKey === "palette" ? [prop] : [],
  ),
);

// Only the positions that produce a value: a condition, a call's argument or a key is not a colour.
const valueSources = (node: ts.Node, constants: Map<string, ts.Node[]>): readonly ts.Node[] => {
  if (ts.isConditionalExpression(node)) return [node.whenTrue, node.whenFalse];
  if (ts.isObjectLiteralExpression(node)) return node.properties;
  if (ts.isArrayLiteralExpression(node)) return node.elements;
  if (ts.isIdentifier(node)) return constants.get(node.text) ?? [];
  if (ts.isBinaryExpression(node)) {
    const operator = node.operatorToken.kind;
    if (operator === ts.SyntaxKind.AmpersandAmpersandToken) return [node.right];
    const isFallback =
      operator === ts.SyntaxKind.BarBarToken || operator === ts.SyntaxKind.QuestionQuestionToken;
    return isFallback ? [node.left, node.right] : [];
  }
  const isWrapper =
    ts.isJsxExpression(node) ||
    ts.isParenthesizedExpression(node) ||
    ts.isAsExpression(node) ||
    ts.isSatisfiesExpression(node) ||
    ts.isSpreadAssignment(node);
  return isWrapper && node.expression ? [node.expression] : [];
};

// Reads only what reaches sx: `sx` attributes and keys, and the same-file constants they name.
// Imports, calls, callbacks, `.` and `[]` access and array spreads are not followed.
const paletteValues = (path: string, text: string) => {
  const constants = new Map<string, ts.Node[]>();
  const sxValues: ts.Node[] = [];
  const collect = (node: ts.Node) => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      const sameName = constants.get(node.name.text) ?? [];
      constants.set(node.name.text, [...sameName, node.initializer]);
    }
    const isSx =
      (ts.isJsxAttribute(node) || ts.isPropertyAssignment(node)) &&
      ts.isIdentifier(node.name) &&
      node.name.text === "sx";
    if (isSx && node.initializer) sxValues.push(node.initializer);
    ts.forEachChild(node, collect);
  };
  collect(ts.createSourceFile(path, text, ts.ScriptTarget.Latest));

  const values: { prop: string; value: string }[] = [];
  const read = (node: ts.Node, enclosing?: string) => {
    if (ts.isStringLiteralLike(node)) {
      if (enclosing) values.push({ prop: enclosing, value: node.text });
    } else if (ts.isPropertyAssignment(node) || ts.isShorthandPropertyAssignment(node)) {
      const prop = ts.isIdentifier(node.name) ? node.name.text : "";
      const value = ts.isPropertyAssignment(node) ? node.initializer : node.name;
      read(value, PALETTE_PROPS.has(prop) ? prop : enclosing);
    } else {
      for (const source of valueSources(node, constants)) read(source, enclosing);
    }
  };
  for (const value of sxValues) read(value);
  return values;
};

const sourcePaletteValues = () =>
  Object.entries(styleSources).flatMap(([path, text]) => paletteValues(path, text));

// sx swaps a token it knows for a variable and passes anything else on, which the browser drops
// unless it is a CSS colour of its own.
const isUnknownToken = ({ prop, value }: { prop: string; value: string }) =>
  !/^(inherit|transparent|currentColor)$|^#|\(/.test(value) &&
  !Object.values(theme.unstable_sx({ [prop]: value })).every((resolved) =>
    String(resolved).startsWith("var("),
  );

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

test.each<[string, string, string[]]>([
  ["a nested selector", `<a sx={{ "&:hover": { color: "divider" } }} />`, ["divider"]],
  ["a responsive value", `<a sx={{ color: { "@media print": "divider" } }} />`, ["divider"]],
  [
    "a ternary with a string comparison",
    `<a sx={{ color: kind === "failed" ? "error.main" : "divider" }} />`,
    ["error.main", "divider"],
  ],
  ["the right side of &&", `<a sx={{ color: kind === "a" && "divider" }} />`, ["divider"]],
  ["both sides of ||", `<a sx={{ color: "divider" || pick("a") || "b" }} />`, ["divider", "b"]],
  ["both sides of ??", `<a sx={{ color: "divider" ?? pick("a") ?? "b" }} />`, ["divider", "b"]],
  ["an array item", `<a sx={{ color: [pick("a"), "divider"] }} />`, ["divider"]],
  ["parentheses", `<a sx={{ color: (kind === "a" && "divider") }} />`, ["divider"]],
  ["an as expression", `<a sx={{ color: "divider" as "a" }} />`, ["divider"]],
  ["a satisfies expression", `<a sx={{ color: "divider" satisfies "a" }} />`, ["divider"]],
  ["a constant passed to sx", `const a = { color: "divider" }; <a sx={a} />`, ["divider"]],
  ["a constant spread into sx", `const a = { color: "b" }; <a sx={{ ...a }} />`, ["b"]],
  ["a constant declared later", `<a sx={a} />; const a = { color: "divider" };`, ["divider"]],
  ["a constant in an sx array", `const a = { color: "b" }; <a sx={[on && a]} />`, ["b"]],
  ["a constant value", `const a = "divider"; <a sx={{ color: a }} />`, ["divider"]],
  ["a shorthand value", `const color = "divider"; <a sx={{ color }} />`, ["divider"]],
  ["a slot's sx", `<a slotProps={{ b: { color: "c", sx: { color: "d" } } }} />`, ["d"]],
  ["a call's arguments", `<a sx={{ bgcolor: alpha("#000", 0.1) }} />`, []],
  ["a props object", `const chip = { label: "x", color: "success" as const };`, []],
  ["an object not passed to sx", `const a = { color: "b" }; <a style={a} />`, []],
])("the scan reads only the palette values of %s", (_, source, expected) => {
  // Arrange
  const path = "source.tsx";

  // Act
  const values = paletteValues(path, source);

  // Assert
  expect(values.map(({ value }) => value)).toEqual(expected);
});

test.each([
  ["tint.missing", true],
  ["dividr", true],
  ["tint", true],
  ["tint.main", false],
  ["divider", false],
  ["currentColor", false],
  ["#000", false],
  ["rgb(var(--mui-palette-error-mainChannel) / 6%)", false],
])("an sx colour of %s counts as unknown: %s", (value, expected) => {
  // Arrange
  const usage = { prop: "bgcolor", value };

  // Act
  const unknown = isUnknownToken(usage);

  // Assert
  expect(unknown).toBe(expected);
});

test("the app's sources are read with palette tokens in them", () => {
  // Arrange
  const expected = { prop: "bgcolor", value: "tint.main" };

  // Act
  const values = sourcePaletteValues();

  // Assert
  expect(values).toContainEqual(expected);
});

test("every palette token the app's sources use exists", () => {
  // Arrange
  const values = sourcePaletteValues();

  // Act
  const unknown = values.filter(isUnknownToken);

  // Assert
  expect(unknown).toEqual([]);
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
