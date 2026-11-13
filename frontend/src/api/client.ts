/**
 * Small fetch wrapper for the ChronoVision backend.
 *
 * - Always same-origin + credentials so the HttpOnly session cookie is sent.
 * - Reads the readable CSRF cookie and echoes it in `X-CSRF-Token` on state-changing
 *   requests (the backend rejects cookie-authenticated writes without it).
 * - Normalises the backend's `{ detail }` error shape into `ApiError`.
 */

export const CSRF_COOKIE_NAME = 'chronovision_csrf';
export const UNAUTHORIZED_EVENT = 'chronovision:unauthorized';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
  }
}

export function readCookie(name: string, cookieSource = document.cookie): string | null {
  if (!cookieSource) return null;
  for (const part of cookieSource.split(';')) {
    const [rawKey, ...rawValue] = part.trim().split('=');
    if (rawKey === name) return decodeURIComponent(rawValue.join('='));
  }
  return null;
}

function dispatchUnauthorized(): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
  }
}

async function parseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === 'string') return body.detail;
  } catch {
    /* non-JSON error body */
  }
  return response.statusText || `Request failed with status ${response.status}`;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase();
  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers };

  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  if (!SAFE_METHODS.has(method)) {
    const csrf = readCookie(CSRF_COOKIE_NAME);
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    credentials: 'same-origin',
    signal: options.signal,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  if (!response.ok) {
    const detail = await parseError(response);
    if (response.status === 401 && path !== '/api/auth/login') {
      dispatchUnauthorized();
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}
