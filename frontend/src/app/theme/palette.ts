import type { PaletteOptions } from "@mui/material/styles";

interface TintColor {
  main: string;
  contrastText: string;
}

declare module "@mui/material/styles" {
  interface TypeBackground {
    subtle: string;
  }
  interface Palette {
    tint: TintColor;
  }
  interface PaletteOptions {
    tint?: TintColor;
  }
}

export const lightPalette: PaletteOptions = {
  primary: { main: "#0f766e", dark: "#115e59", contrastText: "#ffffff" },
  tint: { main: "#dcefeb", contrastText: "#115e59" },
  text: { primary: "#202522", secondary: "#64706a" },
  divider: "#dde2dc",
  background: { default: "#f6f4ef", paper: "#ffffff", subtle: "#f5f8f6" },
  success: { main: "#317451" },
  warning: { main: "#9a6218" },
  error: { main: "#8a332b" },
};

export const darkPalette: PaletteOptions = {
  primary: { main: "#4fbfae", dark: "#3aa596", contrastText: "#0b1d1a" },
  tint: { main: "#183a35", contrastText: "#9fe1d6" },
  text: { primary: "#e4e9e6", secondary: "#a2ada7" },
  divider: "#2f3733",
  background: { default: "#111513", paper: "#181d1b", subtle: "#1f2522" },
  success: { main: "#6bbf8e" },
  warning: { main: "#e0a75a" },
  error: { main: "#f19b91" },
};
