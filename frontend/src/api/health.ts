import { request } from './client';
import type { HealthStatus } from './types';

export function getHealth(): Promise<HealthStatus> {
  return request<HealthStatus>('/api/health');
}
