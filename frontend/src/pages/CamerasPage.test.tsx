import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import { CamerasPage } from './CamerasPage';
import { renderWithProviders } from '../test/render';
import { cameraFixture, livePlaybackFixture, monitoringStatusFixture } from '../test/fixtures';
import * as camerasApi from '../api/cameras';
import * as liveApi from '../api/live';
import * as monitoringApi from '../api/monitoring';

vi.mock('../api/cameras', () => ({
  listCameras: vi.fn(),
  getCamera: vi.fn(),
  createCamera: vi.fn(),
  updateCamera: vi.fn(),
}));
vi.mock('../api/live', () => ({
  getLivePlayback: vi.fn(),
  startLivePlayback: vi.fn(),
}));
vi.mock('../api/monitoring', () => ({
  getMonitoringStatus: vi.fn(),
  startMonitoring: vi.fn(),
  pauseMonitoring: vi.fn(),
  stopMonitoring: vi.fn(),
}));

function renderCameras() {
  return renderWithProviders(
    <Routes>
      <Route path="/cameras" element={<CamerasPage />} />
    </Routes>,
    { route: '/cameras' },
  );
}

describe('CamerasPage', () => {
  beforeEach(() => {
    vi.mocked(camerasApi.listCameras).mockResolvedValue([cameraFixture]);
    vi.mocked(monitoringApi.getMonitoringStatus).mockResolvedValue(monitoringStatusFixture);
    vi.mocked(monitoringApi.startMonitoring).mockResolvedValue({ state: 'running', affected: 1 });
    vi.mocked(camerasApi.createCamera).mockResolvedValue(cameraFixture);
    vi.mocked(liveApi.startLivePlayback).mockResolvedValue(livePlaybackFixture);
    vi.mocked(liveApi.getLivePlayback).mockResolvedValue(livePlaybackFixture);
  });

  it('never starts monitoring merely by opening the page', async () => {
    renderCameras();
    await screen.findByText(cameraFixture.name);
    expect(monitoringApi.startMonitoring).not.toHaveBeenCalled();
  });

  it('starts monitoring only on an explicit click', async () => {
    const user = userEvent.setup();
    renderCameras();
    await screen.findByText(cameraFixture.name);

    await user.click(screen.getByRole('button', { name: 'Start' }));

    await waitFor(() => expect(monitoringApi.startMonitoring).toHaveBeenCalledTimes(1));
  });

  it('rejects invalid JSON configuration before calling the API', async () => {
    const user = userEvent.setup();
    renderCameras();
    await screen.findByText(cameraFixture.name);

    await user.click(screen.getByRole('button', { name: 'Add camera' }));
    await user.type(await screen.findByLabelText(/Name/), 'New Cam');
    await user.type(screen.getByLabelText('Stream reference'), 'rtsp://host/stream');
    await user.click(screen.getByText('Advanced: configuration (JSON)'));
    fireEvent.change(screen.getByLabelText('Configuration (JSON)'), {
      target: { value: '{invalid' },
    });
    await user.click(screen.getByRole('button', { name: 'Create' }));

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(camerasApi.createCamera).not.toHaveBeenCalled();
  });

  it('creates a camera with a valid payload', async () => {
    const user = userEvent.setup();
    renderCameras();
    await screen.findByText(cameraFixture.name);

    await user.click(screen.getByRole('button', { name: 'Add camera' }));
    await user.type(await screen.findByLabelText(/Name/), 'New Cam');
    await user.type(screen.getByLabelText('Stream reference'), 'rtsp://host/stream');
    await user.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() =>
      expect(camerasApi.createCamera).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'New Cam',
          stream_reference: 'rtsp://host/stream',
          enabled: true,
          configuration: {},
        }),
      ),
    );
  });

  it('sends write-only credentials when a pair is provided', async () => {
    const user = userEvent.setup();
    renderCameras();
    await screen.findByText(cameraFixture.name);

    await user.click(screen.getByRole('button', { name: 'Add camera' }));
    await user.type(await screen.findByLabelText(/Name/), 'New Cam');
    await user.type(screen.getByLabelText('Stream reference'), 'rtsp://host/stream');
    await user.type(screen.getByLabelText('Stream username'), 'operator');
    await user.type(screen.getByLabelText('Stream password'), 'secret');
    await user.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() =>
      expect(camerasApi.createCamera).toHaveBeenCalledWith(
        expect.objectContaining({ stream_username: 'operator', stream_password: 'secret' }),
      ),
    );
  });

  it('rejects an incomplete credential pair before calling the API', async () => {
    const user = userEvent.setup();
    renderCameras();
    await screen.findByText(cameraFixture.name);

    await user.click(screen.getByRole('button', { name: 'Add camera' }));
    await user.type(await screen.findByLabelText(/Name/), 'New Cam');
    await user.type(screen.getByLabelText('Stream reference'), 'rtsp://host/stream');
    await user.type(screen.getByLabelText('Stream username'), 'operator');
    await user.click(screen.getByRole('button', { name: 'Create' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Stream username and password must be provided together.',
    );
    expect(camerasApi.createCamera).not.toHaveBeenCalled();
  });

  it('falls back to stored evidence when live playback is unavailable', async () => {
    const user = userEvent.setup();
    const unavailable = {
      available: false,
      state: 'unavailable' as const,
      protocol: null,
      path: null,
      whep_url: null,
      detail: 'live playback is not configured',
    };
    vi.mocked(liveApi.startLivePlayback).mockResolvedValue(unavailable);
    vi.mocked(liveApi.getLivePlayback).mockResolvedValue(unavailable);

    renderCameras();
    await screen.findByText(cameraFixture.name);
    await user.click(screen.getByRole('button', { name: 'Live' }));

    await waitFor(() => expect(liveApi.startLivePlayback).toHaveBeenCalledWith(cameraFixture.id));
    expect(await screen.findByText(/Live playback is unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/Stored snapshots and clips/)).toBeInTheDocument();
  });

  it('does not call the live API until the dialog is opened', async () => {
    renderCameras();
    await screen.findByText(cameraFixture.name);
    expect(liveApi.getLivePlayback).not.toHaveBeenCalled();
    expect(liveApi.startLivePlayback).not.toHaveBeenCalled();
  });
});
