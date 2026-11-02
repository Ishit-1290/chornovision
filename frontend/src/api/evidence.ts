import { apiUrl, request } from './client';
import type { Evidence, RetentionTarget } from './types';

export function updateEvidenceRetention(
  evidenceId: number,
  retentionStatus: RetentionTarget,
): Promise<Evidence> {
  return request<Evidence>(`/api/evidence/${evidenceId}`, {
    method: 'PATCH',
    body: { retention_status: retentionStatus },
  });
}

/**
 * Evidence bytes are fetched through the same authorized endpoint as the rest of the API.
 * Using the URL directly in an `<img>`/`<video>` keeps the session cookie on the request;
 * no evidence path or file is ever exposed to the browser.
 */
export function evidenceUrl(evidenceId: number): string {
  return apiUrl(`/api/evidence/${evidenceId}`);
}
