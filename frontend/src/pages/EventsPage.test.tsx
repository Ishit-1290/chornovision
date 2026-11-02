import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';

import { EventsPage } from './EventsPage';
import { renderWithProviders } from '../test/render';
import { cameraFixture, eventListItemFixture } from '../test/fixtures';
import * as camerasApi from '../api/cameras';
import * as eventsApi from '../api/events';

vi.mock('../api/cameras', () => ({ listCameras: vi.fn() }));
vi.mock('../api/events', () => ({
  listEvents: vi.fn(),
  getEvent: vi.fn(),
  reviewEvent: vi.fn(),
}));

function renderEvents() {
  return renderWithProviders(
    <Routes>
      <Route path="/events" element={<EventsPage />} />
    </Routes>,
    { route: '/events' },
  );
}

describe('EventsPage', () => {
  beforeEach(() => {
    vi.mocked(camerasApi.listCameras).mockResolvedValue([cameraFixture]);
    vi.mocked(eventsApi.listEvents).mockResolvedValue({
      items: [eventListItemFixture],
      total: 1,
      limit: 25,
      offset: 0,
    });
  });

  it('lists events with a default newest-first query', async () => {
    renderEvents();
    expect(await screen.findByText(eventListItemFixture.message)).toBeInTheDocument();

    expect(eventsApi.listEvents).toHaveBeenCalledWith(
      expect.objectContaining({ order: 'desc', limit: 25, offset: 0 }),
    );
  });

  it('re-queries with a since filter when the filter changes', async () => {
    renderEvents();
    await screen.findByText(eventListItemFixture.message);

    fireEvent.change(screen.getByLabelText('Since'), { target: { value: '2026-01-02T03:04' } });

    await waitFor(() => {
      expect(eventsApi.listEvents).toHaveBeenLastCalledWith(
        expect.objectContaining({ since: expect.any(String), offset: 0 }),
      );
    });
  });
});
