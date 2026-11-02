/** Deterministic display helpers. No generated text — only formatting of stored values. */

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString();
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleTimeString();
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes} min ${remainder} s`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

export function formatConfidence(confidence: number | null | undefined): string {
  if (confidence === null || confidence === undefined) return '—';
  return `${Math.round(confidence * 100)}%`;
}

/** Convert an event type identifier into a human label. */
export function humanizeEventType(eventType: string): string {
  return eventType.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

/** Convert a snake_case identifier into a capitalised label. */
export function humanizeToken(token: string): string {
  return token.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

/** RFC3339 timestamp for a `datetime-local`-free "since" filter (ISO date is enough). */
export function isoDate(value: string): string | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return undefined;
  return date.toISOString();
}
