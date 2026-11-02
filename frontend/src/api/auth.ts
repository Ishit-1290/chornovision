import { request } from './client';
import type { LoginResponse, User } from './types';

export function login(username: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>('/api/auth/login', {
    method: 'POST',
    body: { username, password },
  });
}

export function logout(): Promise<{ detail: string }> {
  return request<{ detail: string }>('/api/auth/logout', { method: 'POST' });
}

export function me(): Promise<User> {
  return request<User>('/api/auth/me');
}
