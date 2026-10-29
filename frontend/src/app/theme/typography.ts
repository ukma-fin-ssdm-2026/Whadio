import type { Breakpoints, TypographyVariantsOptions } from "@mui/material/styles";

export const typography = (breakpoints: Breakpoints): TypographyVariantsOptions => ({
  fontFamily:
    '"Inter Variable", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  h1: {
    fontSize: "1.75rem",
    fontWeight: 600,
    lineHeight: 1.25,
    letterSpacing: "-0.01em",
    [breakpoints.up("md")]: { fontSize: "2rem" },
  },
  h2: { fontSize: "1.5rem", fontWeight: 600, lineHeight: 1.3, letterSpacing: 0 },
  h3: { fontSize: "1.25rem", fontWeight: 600, lineHeight: 1.35, letterSpacing: 0 },
  h4: { fontSize: "1.125rem", fontWeight: 600, lineHeight: 1.4, letterSpacing: 0 },
  subtitle1: { fontSize: "1rem", fontWeight: 500, lineHeight: 1.5, letterSpacing: 0 },
  subtitle2: { fontSize: "0.875rem", fontWeight: 500, lineHeight: 1.45, letterSpacing: 0 },
  body1: { fontSize: "1rem", fontWeight: 400, lineHeight: 1.5, letterSpacing: 0 },
  body2: { fontSize: "0.875rem", fontWeight: 400, lineHeight: 1.45, letterSpacing: 0 },
  caption: { fontSize: "0.75rem", fontWeight: 400, lineHeight: 1.4, letterSpacing: 0 },
  overline: {
    fontSize: "0.75rem",
    fontWeight: 600,
    lineHeight: 1.5,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  button: {
    fontSize: "0.875rem",
    fontWeight: 500,
    lineHeight: 1.5,
    letterSpacing: 0,
    textTransform: "none",
  },
});
