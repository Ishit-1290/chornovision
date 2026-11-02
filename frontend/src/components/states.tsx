import { Alert, Box, CircularProgress, Stack } from '@mui/material';
import type { ReactNode } from 'react';

import { ApiError } from '../api/client';

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <Stack spacing={2} sx={{ py: 6, alignItems: 'center' }}>
      <CircularProgress size={28} />
      <Box color="text.secondary">{label}</Box>
    </Stack>
  );
}

/** Render a backend error honestly (status + detail) instead of inventing a message. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const detail =
    error instanceof ApiError
      ? `${error.message} (HTTP ${error.status})`
      : error instanceof Error
        ? error.message
        : 'Unexpected error';
  return (
    <Alert
      severity="error"
      action={
        onRetry ? (
          <Box
            component="button"
            onClick={onRetry}
            sx={{ border: 0, background: 'none', cursor: 'pointer' }}
          >
            Retry
          </Box>
        ) : undefined
      }
    >
      {detail}
    </Alert>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <Box sx={{ py: 6, textAlign: 'center', color: 'text.secondary' }}>{children}</Box>;
}
