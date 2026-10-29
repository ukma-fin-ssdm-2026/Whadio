import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type { ReactElement, ReactNode } from "react";
import { NotifyProvider } from "../ui/NotifyProvider";

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

interface TestProvidersProps {
  queryClient: QueryClient;
  children: ReactNode;
}

// Shared code may not import the app's theme, so components render with MUI's default one.
export function TestProviders({ queryClient, children }: TestProvidersProps) {
  return (
    <QueryClientProvider client={queryClient}>
      <NotifyProvider>{children}</NotifyProvider>
    </QueryClientProvider>
  );
}

export function renderWithProviders(ui: ReactElement, queryClient = createTestQueryClient()) {
  const user = userEvent.setup();
  const rendered = render(ui, {
    wrapper: ({ children }) => <TestProviders queryClient={queryClient}>{children}</TestProviders>,
  });
  return { ...rendered, user, queryClient };
}
