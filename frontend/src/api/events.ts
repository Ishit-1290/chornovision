import { request } from './client';
import type { EventDetail, EventListResponse, EventQuery, ReviewStatus } from './types';

function buildQuery(query: EventQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : '';
}

export function listEvents(query: EventQuery = {}): Promise<EventListResponse> {
  return request<EventListResponse>(`/api/events${buildQuery(query)}`);
}

export function getEvent(eventId: number): Promise<EventDetail> {
  return request<EventDetail>(`/api/events/${eventId}`);
}

export function reviewEvent(
  eventId: number,
  reviewStatus: ReviewStatus,
  note?: string,
): Promise<EventDetail> {
  return request<EventDetail>(`/api/events/${eventId}`, {
    method: 'PATCH',
    body: { review_status: reviewStatus, note },
  });
}
