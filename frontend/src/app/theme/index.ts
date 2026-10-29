import { createTheme } from "@mui/material/styles";
import { components } from "./components";
import { darkPalette, lightPalette } from "./palette";
import { typography } from "./typography";

declare module "@mui/material/styles" {
  interface CssThemeVariables {
    enabled: true;
  }
}

const { breakpoints } = createTheme();

export const theme = createTheme({
  cssVariables: true,
  colorSchemes: { light: { palette: lightPalette }, dark: { palette: darkPalette } },
  typography: typography(breakpoints),
  shape: { borderRadius: 8 },
  components,
});
