import { request } from './client';
import type { SystemSettings } from './types';

export function getSettings(): Promise<SystemSettings> {
  return request<SystemSettings>('/api/settings');
}
