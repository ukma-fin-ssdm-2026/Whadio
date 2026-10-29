import { CssBaseline, ThemeProvider } from "@mui/material";
import { QueryClientProvider } from "@tanstack/react-query";
import { lazy, type ReactNode, Suspense, useLayoutEffect, useRef, useState } from "react";
import { createQueryClient } from "./query-client";
import { theme } from "./theme";

const ReactQueryDevtools =
  import.meta.env.MODE === "development"
    ? lazy(() =>
        import("@tanstack/react-query-devtools").then((module) => ({
          default: module.ReactQueryDevtools,
        })),
      )
    : null;

interface AppProvidersProps {
  onUnauthorized: () => void;
  children: ReactNode;
}

export function AppProviders({ onUnauthorized, children }: AppProvidersProps) {
  // The client lives as long as the app, so it reads the handler through a ref to call the latest.
  const latestOnUnauthorized = useRef(onUnauthorized);
  useLayoutEffect(() => {
    latestOnUnauthorized.current = onUnauthorized;
  });
  const [queryClient] = useState(() =>
    createQueryClient({ onUnauthorized: () => latestOnUnauthorized.current() }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <CssBaseline enableColorScheme />
        {children}
      </ThemeProvider>
      {ReactQueryDevtools && (
        <Suspense>
          <ReactQueryDevtools buttonPosition="bottom-right" />
        </Suspense>
      )}
    </QueryClientProvider>
  );
}
