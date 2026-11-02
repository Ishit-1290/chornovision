import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  ApiError,
  CSRF_COOKIE_NAME,
  UNAUTHORIZED_EVENT,
  apiUrl,
  readCookie,
  request,
} from './client';

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: async () => body,
  } as unknown as Response;
}

function emptyResponse(status: number): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => {
      throw new Error('no body');
    },
  } as unknown as Response;
}

describe('api client', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    document.cookie = `${CSRF_COOKIE_NAME}=; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('reads the CSRF cookie value', () => {
    expect(readCookie(CSRF_COOKIE_NAME, `${CSRF_COOKIE_NAME}=abc%20123`)).toBe('abc 123');
    expect(readCookie(CSRF_COOKIE_NAME, 'other=1')).toBeNull();
    expect(readCookie(CSRF_COOKIE_NAME, '')).toBeNull();
  });

  it('sends same-origin credentials and no CSRF header for GET', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await request('/api/health');

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/health');
    expect(init.credentials).toBe('same-origin');
    expect(init.method).toBe('GET');
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBeUndefined();
  });

  it('echoes the CSRF cookie on state-changing requests', async () => {
    document.cookie = `${CSRF_COOKIE_NAME}=token-value`;
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await request('/api/cameras', { method: 'POST', body: { name: 'x' } });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers['X-CSRF-Token']).toBe('token-value');
    expect(headers['Content-Type']).toBe('application/json');
    expect(init.body).toBe(JSON.stringify({ name: 'x' }));
  });

  it('normalises the backend detail error into ApiError', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Camera not found' }, 404));
    await expect(request('/api/cameras/9')).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
      message: 'Camera not found',
    });
  });

  it('dispatches the unauthorized event on 401 responses', async () => {
    const handler = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, handler);
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Not authenticated' }, 401));

    await expect(request('/api/events')).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledTimes(1);

    window.removeEventListener(UNAUTHORIZED_EVENT, handler);
  });

  it('does not dispatch unauthorized for a failed login attempt', async () => {
    const handler = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, handler);
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Invalid' }, 401));

    await expect(request('/api/auth/login', { method: 'POST', body: {} })).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(handler).not.toHaveBeenCalled();

    window.removeEventListener(UNAUTHORIZED_EVENT, handler);
  });

  it('returns undefined for 204 responses', async () => {
    fetchMock.mockResolvedValue(emptyResponse(204));
    await expect(request('/api/evidence/1', { method: 'PATCH' })).resolves.toBeUndefined();
  });

  it('builds api URLs', () => {
    expect(apiUrl('/api/evidence/3')).toBe('/api/evidence/3');
  });
});
