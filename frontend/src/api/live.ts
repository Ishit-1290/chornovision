import { request } from './client';
import type { LivePlaybackInfo } from './types';

/**
 * Read-only playback status. Returns only the gateway path and WHEP URL — the camera
 * source and credentials stay on the server.
 */
export function getLivePlayback(cameraId: number): Promise<LivePlaybackInfo> {
  return request<LivePlaybackInfo>(`/api/cameras/${cameraId}/live`);
}

/**
 * Reconcile the gateway path for a camera. Idempotent; it does not start monitoring.
 * Requires the session's CSRF token (handled by the shared request wrapper).
 */
export function startLivePlayback(cameraId: number): Promise<LivePlaybackInfo> {
  return request<LivePlaybackInfo>(`/api/cameras/${cameraId}/live/start`, { method: 'POST' });
}
