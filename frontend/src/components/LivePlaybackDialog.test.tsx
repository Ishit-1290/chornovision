import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { LivePlaybackDialog } from './LivePlaybackDialog';
import type { Camera } from '../api/types';
import { cameraFixture, livePlaybackFixture } from '../test/fixtures';
import { renderWithProviders } from '../test/render';
import * as camerasApi from '../api/cameras';
import * as liveApi from '../api/live';

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
// The WHEP connection itself is covered by LivePlayer.test; stub it so the dialog test only
// exercises the rotation wiring (read from `configuration` and persisted via the camera PATCH).
vi.mock('../lib/whep', () => ({
  useWhep: () => ({ status: 'live', error: null, retry: vi.fn() }),
}));

/** A sideways camera whose operator already chose a 90° correction. */
const rotatedCamera: Camera = {
  ...cameraFixture,
  configuration: { zones: [], rotation: 90 },
};

describe('LivePlaybackDialog', () => {
  beforeEach(() => {
    vi.mocked(camerasApi.updateCamera).mockResolvedValue(rotatedCamera);
    vi.mocked(liveApi.getLivePlayback).mockResolvedValue(livePlaybackFixture);
    vi.mocked(liveApi.startLivePlayback).mockResolvedValue(livePlaybackFixture);
  });

  it('starts the player at the camera’s saved rotation', async () => {
    renderWithProviders(<LivePlaybackDialog camera={rotatedCamera} onClose={vi.fn()} />);

    const video = await waitFor(() => {
      const element = document.querySelector('[data-testid="live-player-video"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    expect(video.dataset.rotation).toBe('90');
  });

  it('persists a rotation change through the camera PATCH', async () => {
    const user = userEvent.setup();
    renderWithProviders(<LivePlaybackDialog camera={rotatedCamera} onClose={vi.fn()} />);

    const rotateRight = await waitFor(() => {
      const button = document.querySelector('[aria-label="Rotate right"]');
      expect(button).not.toBeNull();
      return button as HTMLElement;
    });
    await user.click(rotateRight);

    await waitFor(() => expect(camerasApi.updateCamera).toHaveBeenCalledTimes(1));
    const [id, payload] = vi.mocked(camerasApi.updateCamera).mock.calls[0];
    expect(id).toBe(rotatedCamera.id);
    expect(payload.configuration).toMatchObject({ rotation: 180 });
  });
});
