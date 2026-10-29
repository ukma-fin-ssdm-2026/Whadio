import type { Components, CssVarsTheme, Theme } from "@mui/material/styles";

export const components: Components<Omit<Theme, "components" | "palette"> & CssVarsTheme> = {
  MuiCard: {
    styleOverrides: {
      root: ({ theme }) => ({
        border: `1px solid ${theme.vars.palette.divider}`,
        boxShadow: "none",
      }),
    },
  },
  MuiButton: {
    styleOverrides: {
      root: { minHeight: 40 },
    },
  },
  MuiTypography: {
    defaultProps: {
      // MUI renders subtitles as <h6>; they label rows and cards, which are not document headings.
      variantMapping: { subtitle1: "p", subtitle2: "p" },
    },
  },
};
