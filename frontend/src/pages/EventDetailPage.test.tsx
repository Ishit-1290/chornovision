import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import { EventDetailPage } from './EventDetailPage';
import { renderWithProviders } from '../test/render';
import { eventDetailFixture } from '../test/fixtures';
import * as eventsApi from '../api/events';
import * as evidenceApi from '../api/evidence';

vi.mock('../api/events', () => ({
  listEvents: vi.fn(),
  getEvent: vi.fn(),
  reviewEvent: vi.fn(),
}));
vi.mock('../api/evidence', () => ({
  updateEvidenceRetention: vi.fn(),
  evidenceUrl: (id: number) => `/api/evidence/${id}`,
}));

function renderDetail() {
  return renderWithProviders(
    <Routes>
      <Route path="/events/:eventId" element={<EventDetailPage />} />
    </Routes>,
    { route: '/events/1' },
  );
}

describe('EventDetailPage', () => {
  beforeEach(() => {
    vi.mocked(eventsApi.getEvent).mockResolvedValue(eventDetailFixture);
    vi.mocked(eventsApi.reviewEvent).mockResolvedValue({
      ...eventDetailFixture,
      review_status: 'confirmed',
    });
    vi.mocked(evidenceApi.updateEvidenceRetention).mockResolvedValue({
      ...eventDetailFixture.evidence[0],
      retention_status: 'protected',
    });
  });

  it('shows the deterministic message and transition history', async () => {
    renderDetail();
    expect(
      await screen.findByRole('heading', { name: eventDetailFixture.message }),
    ).toBeInTheDocument();
    expect(screen.getByText('Person entering detected.')).toBeInTheDocument();
  });

  it('records a review decision without altering the message', async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByRole('heading', { name: eventDetailFixture.message });

    await user.click(screen.getByRole('button', { name: 'Confirm' }));

    expect(eventsApi.reviewEvent).toHaveBeenCalledWith(1, 'confirmed', undefined);
  });

  it('protects evidence from deletion', async () => {
    const user = userEvent.setup();
    renderDetail();
    await screen.findByRole('heading', { name: eventDetailFixture.message });

    await user.click(screen.getByRole('button', { name: 'Protect from deletion' }));

    expect(evidenceApi.updateEvidenceRetention).toHaveBeenCalledWith(10, 'protected');
  });
});
