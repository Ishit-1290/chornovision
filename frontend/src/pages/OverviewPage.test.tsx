import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';

import { OverviewPage } from './OverviewPage';
import { renderWithProviders } from '../test/render';
import { cameraFixture, monitoringStatusFixture, settingsFixture } from '../test/fixtures';
import * as camerasApi from '../api/cameras';
import * as eventsApi from '../api/events';
import * as healthApi from '../api/health';
import * as monitoringApi from '../api/monitoring';
import * as settingsApi from '../api/settings';

vi.mock('../api/cameras', () => ({ listCameras: vi.fn() }));
vi.mock('../api/events', () => ({ listEvents: vi.fn() }));
vi.mock('../api/health', () => ({ getHealth: vi.fn() }));
vi.mock('../api/monitoring', () => ({
  getMonitoringStatus: vi.fn(),
  startMonitoring: vi.fn(),
  pauseMonitoring: vi.fn(),
  stopMonitoring: vi.fn(),
}));
vi.mock('../api/settings', () => ({ getSettings: vi.fn() }));

function renderOverview() {
  return renderWithProviders(
    <Routes>
      <Route path="/" element={<OverviewPage />} />
    </Routes>,
    { route: '/' },
  );
}

describe('OverviewPage live-playback notice', () => {
  beforeEach(() => {
    vi.mocked(healthApi.getHealth).mockResolvedValue({
      status: 'ok',
      app_name: 'ChronoVision',
      environment: 'test',
      database: 'ok',
    });
    vi.mocked(monitoringApi.getMonitoringStatus).mockResolvedValue(monitoringStatusFixture);
    vi.mocked(camerasApi.listCameras).mockResolvedValue([cameraFixture]);
    vi.mocked(eventsApi.listEvents).mockResolvedValue({
      items: [],
      total: 0,
      limit: 5,
      offset: 0,
    });
  });

  it('states that live playback is unavailable when no gateway is configured', async () => {
    vi.mocked(settingsApi.getSettings).mockResolvedValue({
      ...settingsFixture,
      live_playback_enabled: false,
    });
    renderOverview();

    expect(await screen.findByText(/Live video playback is not available/)).toBeInTheDocument();
    expect(screen.getByText(/Only stored snapshot and clip evidence/)).toBeInTheDocument();
  });

  it('points to the live view when a gateway is configured', async () => {
    vi.mocked(settingsApi.getSettings).mockResolvedValue({
      ...settingsFixture,
      live_playback_enabled: true,
    });
    renderOverview();

    expect(await screen.findByText(/Live playback is enabled/)).toBeInTheDocument();
    expect(screen.queryByText(/Live video playback is not available/)).not.toBeInTheDocument();
  });
});
