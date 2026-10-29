import MenuRoundedIcon from "@mui/icons-material/MenuRounded";
import {
  AppBar,
  Box,
  Container,
  Drawer,
  IconButton,
  Toolbar,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import { type ReactNode, useState } from "react";

const DRAWER_WIDTH = 260;

interface AppShellProps {
  renderSidebar: (onNavigate: () => void) => ReactNode;
  children: ReactNode;
}

export function AppShell({ renderSidebar, children }: AppShellProps) {
  const desktop = useMediaQuery(useTheme().breakpoints.up("md"), { noSsr: true });
  const [drawerOpen, setDrawerOpen] = useState(false);
  const closeDrawer = () => setDrawerOpen(false);

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <Drawer
        variant={desktop ? "permanent" : "temporary"}
        open={desktop || drawerOpen}
        onClose={closeDrawer}
        sx={{
          width: { md: DRAWER_WIDTH },
          flexShrink: 0,
          "& .MuiDrawer-paper": { width: DRAWER_WIDTH, boxSizing: "border-box" },
        }}
      >
        {renderSidebar(closeDrawer)}
      </Drawer>
      <Box sx={{ flexGrow: 1, minWidth: 0 }}>
        {!desktop && (
          <AppBar position="static" color="inherit" elevation={0}>
            <Toolbar sx={{ gap: 1, borderBottom: 1, borderColor: "divider" }}>
              <IconButton
                edge="start"
                aria-label="Open navigation"
                onClick={() => setDrawerOpen(true)}
              >
                <MenuRoundedIcon />
              </IconButton>
              <Typography variant="h4" component="p">
                Whadio
              </Typography>
            </Toolbar>
          </AppBar>
        )}
        <Container component="main" maxWidth="lg" sx={{ py: { xs: 2, md: 3 } }}>
          {children}
        </Container>
      </Box>
    </Box>
  );
}
