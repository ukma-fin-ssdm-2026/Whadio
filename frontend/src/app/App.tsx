import { RouterProvider } from "@tanstack/react-router";
import { useState } from "react";
import { createApp } from "./create-app";
import { AppProviders } from "./providers";

export function App({ basepath }: { basepath?: string }) {
  const [{ queryClient, router }] = useState(() => createApp(basepath));
  return (
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>
  );
}
