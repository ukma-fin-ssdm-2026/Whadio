import type { Components, CssVarsTheme, Theme } from "@mui/material/styles";

export const components: Components<Omit<Theme, "components" | "palette"> & CssVarsTheme> = {
  MuiCssBaseline: {
    styleOverrides: (theme) => ({
      body: {
        minWidth: 320,
        backgroundImage: `linear-gradient(135deg, rgb(${theme.vars.palette.primary.mainChannel} / 7%), transparent 34rem)`,
      },
    }),
  },
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
