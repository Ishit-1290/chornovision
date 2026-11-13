import { request } from './client';
import type { Camera } from './types';

export interface CameraCreatePayload {
  name: string;
  stream_reference: string;
  enabled?: boolean;
  configuration?: Record<string, unknown>;
  /** Write-only; encrypted at rest by the backend. Must be sent together. */
  stream_username?: string;
  stream_password?: string;
}

export interface CameraUpdatePayload {
  name?: string;
  stream_reference?: string;
  enabled?: boolean;
  configuration?: Record<string, unknown>;
  /** Write-only; encrypted at rest by the backend. Must be sent together. */
  stream_username?: string;
  stream_password?: string;
  clear_stream_credentials?: boolean;
}

export function listCameras(): Promise<Camera[]> {
  return request<Camera[]>('/api/cameras');
}

export function createCamera(payload: CameraCreatePayload): Promise<Camera> {
  return request<Camera>('/api/cameras', { method: 'POST', body: payload });
}

export function updateCamera(cameraId: number, payload: CameraUpdatePayload): Promise<Camera> {
  return request<Camera>(`/api/cameras/${cameraId}`, { method: 'PATCH', body: payload });
}
