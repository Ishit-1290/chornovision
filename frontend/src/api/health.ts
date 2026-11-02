import { request } from './client';
import type { CameraHealthResponse, HealthStatus } from './types';

export function getHealth(): Promise<HealthStatus> {
  return request<HealthStatus>('/api/health');
}

export function getCameraHealth(): Promise<CameraHealthResponse> {
  return request<CameraHealthResponse>('/api/health/cameras');
}
