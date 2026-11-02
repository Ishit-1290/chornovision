import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ZoneSetupWizard } from './ZoneSetupWizard';
import type { Camera } from '../api/types';
import { cameraFixture } from '../test/fixtures';
import { renderWithProviders } from '../test/render';
import { ApiError } from '../api/client';
import * as camerasApi from '../api/cameras';
import * as monitoringApi from '../api/monitoring';
import * as liveApi from '../api/live';

vi.mock('../api/cameras', () => ({
  listCameras: vi.fn(),
  getCamera: vi.fn(),
  createCamera: vi.fn(),
  updateCamera: vi.fn(),
}));
vi.mock('../api/monitoring', () => ({
  getMonitoringStatus: vi.fn(),
  startMonitoring: vi.fn(),
  pauseMonitoring: vi.fn(),
  stopMonitoring: vi.fn(),
}));
vi.mock('../api/live', () => ({
  getLivePlayback: vi.fn(),
  startLivePlayback: vi.fn(),
}));

const unavailable = {
  available: false,
  state: 'unavailable' as const,
  protocol: null,
  path: null,
  whep_url: null,
  detail: 'not configured',
};

function polygon(size = 0.4) {
  return [
    { x: 0.1, y: 0.1 },
    { x: 0.1 + size, y: 0.1 },
    { x: 0.1 + size, y: 0.1 + size },
    { x: 0.1, y: 0.1 + size },
  ];
}

const configuredCamera: Camera = {
  ...cameraFixture,
  configuration: {
    zones: [
      {
        id: 'entrance-1',
        name: 'Entrance',
        kind: 'entrance',
        polygon: polygon(),
        boundary: { p1: { x: 0.1, y: 0.5 }, p2: { x: 0.9, y: 0.5 }, inside_side: 'left' },
      },
      { id: 'room-1', name: 'Room', kind: 'room', polygon: polygon(0.5) },
    ],
    event_rules: { entrance_zone_id: 'entrance-1', room_zone_id: 'room-1' },
  },
};

/** A camera whose state references an entrance role but has no matching zone. */
const brokenCamera: Camera = {
  ...cameraFixture,
  configuration: {
    zones: [],
    event_rules: { entrance_zone_id: 'ghost' },
  },
};

function renderWizard(camera: Camera) {
  return renderWithProviders(<ZoneSetupWizard camera={camera} onClose={vi.fn()} />);
}

async function goToReview(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Next' }));
  await user.click(screen.getByRole('button', { name: 'Next' }));
  await user.click(screen.getByRole('button', { name: 'Next' }));
}

describe('ZoneSetupWizard', () => {
  beforeEach(() => {
    vi.mocked(camerasApi.updateCamera).mockResolvedValue(configuredCamera);
    vi.mocked(monitoringApi.getMonitoringStatus).mockResolvedValue({
      state: 'stopped',
      running: false,
      counts: {},
      cameras: [],
    });
    vi.mocked(monitoringApi.startMonitoring).mockResolvedValue({ state: 'running', affected: 1 });
    vi.mocked(liveApi.startLivePlayback).mockResolvedValue(unavailable);
    vi.mocked(liveApi.getLivePlayback).mockResolvedValue(unavailable);
  });

  it('shows events with unsupported ones disabled and labelled', () => {
    renderWizard(configuredCamera);
    expect(screen.getByLabelText('Door remains open too long')).toBeDisabled();
    expect(screen.getByLabelText('Falling from bed')).toBeDisabled();
    expect(screen.getAllByText('Not available yet').length).toBeGreaterThanOrEqual(2);
    // Supported events are selectable.
    expect(screen.getByLabelText('Person entering')).not.toBeDisabled();
  });

  it('does not start monitoring merely by opening the wizard', () => {
    renderWizard(configuredCamera);
    expect(monitoringApi.startMonitoring).not.toHaveBeenCalled();
  });

  it('saves the generated configuration and offers to start monitoring', async () => {
    const user = userEvent.setup();
    renderWizard(configuredCamera);
    await goToReview(user);

    await user.click(screen.getByRole('button', { name: 'Save configuration' }));

    await waitFor(() => expect(camerasApi.updateCamera).toHaveBeenCalledTimes(1));
    const [id, payload] = vi.mocked(camerasApi.updateCamera).mock.calls[0];
    expect(id).toBe(configuredCamera.id);
    expect(payload.configuration).toMatchObject({
      zones: expect.arrayContaining([
        expect.objectContaining({ id: 'entrance-1', kind: 'entrance' }),
        expect.objectContaining({ id: 'room-1', kind: 'room' }),
      ]),
      event_rules: expect.objectContaining({
        entrance_zone_id: 'entrance-1',
        room_zone_id: 'room-1',
      }),
    });

    expect(await screen.findByText(/Configuration saved/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Start monitoring' }));
    await waitFor(() => expect(monitoringApi.startMonitoring).toHaveBeenCalledTimes(1));
  });

  it('saves the preview rotation into the configuration', async () => {
    const user = userEvent.setup();
    renderWizard(configuredCamera);

    // Step 1 is the zone editor, which owns the rotate controls.
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(screen.getByRole('button', { name: 'Rotate view right' }));
    expect(screen.getByText('View 90°')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(screen.getByRole('button', { name: 'Save configuration' }));

    await waitFor(() => expect(camerasApi.updateCamera).toHaveBeenCalledTimes(1));
    const [, payload] = vi.mocked(camerasApi.updateCamera).mock.calls[0];
    expect(payload.configuration?.rotation).toBe(90);
  });

  it('surfaces a backend validation error and does not claim success', async () => {
    const user = userEvent.setup();
    vi.mocked(camerasApi.updateCamera).mockRejectedValue(
      new ApiError(422, 'Invalid camera configuration: entrance zone must define a boundary line'),
    );
    renderWizard(configuredCamera);
    await goToReview(user);
    await user.click(screen.getByRole('button', { name: 'Save configuration' }));

    expect(await screen.findByText(/Invalid camera configuration/)).toBeInTheDocument();
    expect(screen.queryByText(/Configuration saved/)).not.toBeInTheDocument();
  });

  it('blocks saving when a required zone is missing', async () => {
    const user = userEvent.setup();
    renderWizard(brokenCamera);
    await goToReview(user);

    expect(screen.getByRole('button', { name: 'Save configuration' })).toBeDisabled();
    expect(screen.getByText(/Draw the Entrance zone/)).toBeInTheDocument();
  });

  it('shows the exact generated JSON in the advanced view', async () => {
    const user = userEvent.setup();
    renderWizard(configuredCamera);
    await goToReview(user);

    await user.click(screen.getByText('Advanced JSON (debugging)'));
    const json = screen.getByTestId('advanced-json').textContent ?? '';
    const parsed = JSON.parse(json) as Record<string, unknown>;
    expect(Object.keys(parsed).sort()).toEqual(['event_rules', 'zones']);
  });
});
