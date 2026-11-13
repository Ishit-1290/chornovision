/**
 * Deterministic error-text helper.
 *
 * Renders a backend error honestly — the server's `detail` plus the HTTP status when the
 * failure came from the API — instead of inventing or hiding a message. Callers supply a
 * fallback for non-`Error` throws (e.g. a rejected non-Error value).
 */

import { ApiError } from '../api/client';

export function formatErrorText(error: unknown, fallback = 'Unexpected error'): string {
  if (error instanceof ApiError) return `${error.message} (HTTP ${error.status})`;
  if (error instanceof Error) return error.message;
  return fallback;
}
