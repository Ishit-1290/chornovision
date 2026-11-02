import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from '@mui/material/styles';

import { LivePlayer } from './LivePlayer';
import { theme } from '../theme';
import type { Rotation } from '../lib/videoRotation';

const WHEP_URL = 'http://gateway.example:8889/cv-cam-1/whep';
const SESSION_URL = 'http://gateway.example:8889/cv-cam-1/whep/secret-session';

class FakePeerConnection {
  static instances: FakePeerConnection[] = [];

  iceGatheringState: RTCIceGatheringState = 'complete';
  connectionState: RTCPeerConnectionState = 'new';
  localDescription: RTCSessionDescription | null = null;
  onconnectionstatechange: (() => void) | null = null;
  ontrack: ((event: RTCTrackEvent) => void) | null = null;
  closed = false;

  constructor(_config: RTCConfiguration) {
    FakePeerConnection.instances.push(this);
  }

  addEventListener(): void {}
  removeEventListener(): void {}
  addTransceiver(): void {}

  async createOffer(): Promise<RTCSessionDescriptionInit> {
    return { type: 'offer', sdp: 'v=0 offer' };
  }

  async setLocalDescription(description: RTCSessionDescriptionInit): Promise<void> {
    this.localDescription = description as RTCSessionDescription;
  }

  async setRemoteDescription(_description: RTCSessionDescriptionInit): Promise<void> {}

  close(): void {
    this.closed = true;
    this.connectionState = 'closed';
  }

  connect(): void {
    this.connectionState = 'connected';
    this.onconnectionstatechange?.();
  }
}

interface FakeResponseInit {
  ok?: boolean;
  status?: number;
  location?: string | null;
  body?: string;
}

function fakeResponse({
  ok = true,
  status = 201,
  location = '/cv-cam-1/whep/secret-session',
  body = 'v=0 answer',
}: FakeResponseInit = {}): Response {
  return {
    ok,
    status,
    headers: {
      get: (name: string) => (name.toLowerCase() === 'location' ? location : null),
    },
    text: async () => body,
  } as unknown as Response;
}

const fetchMock = vi.fn();

function renderPlayer(
  props: { rotation?: Rotation; onRotate?: (rotation: Rotation) => void } = {},
) {
  return render(
    <ThemeProvider theme={theme}>
      <LivePlayer whepUrl={WHEP_URL} {...props} />
    </ThemeProvider>,
  );
}

describe('LivePlayer', () => {
  beforeEach(() => {
    FakePeerConnection.instances = [];
    fetchMock.mockReset();
    vi.stubGlobal('RTCPeerConnection', FakePeerConnection);
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('negotiates WHEP and shows the live state', async () => {
    fetchMock.mockResolvedValue(fakeResponse());
    renderPlayer();

    expect(screen.getByText(/Connecting/)).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(fetchMock.mock.calls[0][0]).toBe(WHEP_URL);
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/sdp');
    expect(String(init.body)).toContain('v=0 offer');
    // No cookies are sent to the (separate-origin) gateway.
    expect(init.credentials).toBe('omit');

    act(() => {
      FakePeerConnection.instances[0].connect();
    });
    expect(await screen.findByText('Live')).toBeInTheDocument();
  });

  it('reports a gateway rejection honestly', async () => {
    fetchMock.mockResolvedValue(fakeResponse({ ok: false, status: 503, location: null }));
    renderPlayer();

    expect(await screen.findByText(/rejected playback \(HTTP 503\)/i)).toBeInTheDocument();
    expect(screen.getAllByText('Playback error').length).toBeGreaterThan(0);
  });

  it('retries on demand', async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue(fakeResponse({ ok: false, status: 502, location: null }));
    renderPlayer();

    await screen.findByText(/rejected playback/i);
    await user.click(screen.getByRole('button', { name: 'Try again' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it('closes the peer connection and deletes the WHEP session on unmount', async () => {
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') return fakeResponse({ status: 200, location: null });
      return fakeResponse();
    });
    const { unmount } = renderPlayer();

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    unmount();

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        SESSION_URL,
        expect.objectContaining({ method: 'DELETE' }),
      ),
    );
    expect(FakePeerConnection.instances[0].closed).toBe(true);
  });

  it('reports a missing WebRTC implementation instead of hanging', async () => {
    vi.stubGlobal('RTCPeerConnection', undefined);
    renderPlayer();
    expect(
      await screen.findByText('This browser does not support WebRTC playback.'),
    ).toBeInTheDocument();
  });

  it('reports rotate requests without renegotiating the stream', async () => {
    const user = userEvent.setup();
    const onRotate = vi.fn();
    fetchMock.mockResolvedValue(fakeResponse());
    renderPlayer({ rotation: 90, onRotate });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const video = screen.getByTestId('live-player-video');
    expect(video.dataset.rotation).toBe('90');
    expect(screen.getByText('90°')).toBeInTheDocument();
    expect(video).toHaveStyle({ transform: 'rotate(90deg)' });

    await user.click(screen.getByRole('button', { name: 'Rotate right' }));
    expect(onRotate).toHaveBeenLastCalledWith(180);

    await user.click(screen.getByRole('button', { name: 'Rotate left' }));
    expect(onRotate).toHaveBeenLastCalledWith(0);

    await user.click(screen.getByRole('button', { name: 'Reset' }));
    expect(onRotate).toHaveBeenLastCalledWith(0);

    // Rotation changes the saved setting only: a single WHEP POST was made on mount.
    const posts = fetchMock.mock.calls.filter(
      (call) => (call[1] as RequestInit)?.method === 'POST',
    );
    expect(posts).toHaveLength(1);
  });

  it('reflects a rotation passed in by the parent', async () => {
    fetchMock.mockResolvedValue(fakeResponse());
    const { rerender } = render(
      <ThemeProvider theme={theme}>
        <LivePlayer whepUrl={WHEP_URL} rotation={0} onRotate={() => {}} />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('live-player-video').dataset.rotation).toBe('0');

    rerender(
      <ThemeProvider theme={theme}>
        <LivePlayer whepUrl={WHEP_URL} rotation={270} onRotate={() => {}} />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('live-player-video').dataset.rotation).toBe('270');
    expect(screen.getByText('270°')).toBeInTheDocument();
    expect(screen.getByTestId('live-player-video')).toHaveStyle({ transform: 'rotate(270deg)' });
  });

  it('disables the rotate controls when no handler is supplied', async () => {
    fetchMock.mockResolvedValue(fakeResponse());
    renderPlayer({ rotation: 90 });

    expect(screen.getByRole('button', { name: 'Rotate right' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Rotate left' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Reset' })).not.toBeInTheDocument();
  });
});
