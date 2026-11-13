import { Alert, Box, CircularProgress, Stack } from '@mui/material';
import type { ReactNode } from 'react';

import { formatErrorText } from '../lib/errors';

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
  const detail = formatErrorText(error);
  return (
    <Alert
      severity="error"
      action={
        onRetry ? (
          <Box
            component="button"
            type="button"
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
