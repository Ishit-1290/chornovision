import { render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from '@mui/material/styles';
import { MemoryRouter } from 'react-router-dom';
import type { ReactElement, ReactNode } from 'react';

import { theme } from '../theme';

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

export function TestProviders({
  children,
  route = '/',
  queryClient = createTestQueryClient(),
}: {
  children: ReactNode;
  route?: string;
  queryClient?: QueryClient;
}) {
  return (
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

export function renderWithProviders(
  ui: ReactElement,
  options: { route?: string; queryClient?: QueryClient } = {},
) {
  const queryClient = options.queryClient ?? createTestQueryClient();
  const result = render(
    <TestProviders route={options.route} queryClient={queryClient}>
      {ui}
    </TestProviders>,
  );
  return { ...result, queryClient };
}
