import { describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';

import { RealtimeProvider } from './RealtimeProvider';
import { useRealtime } from './useRealtime';
import { TestProviders, createTestQueryClient } from '../test/render';
import { userFixture } from '../test/fixtures';
import type { DashboardSocketOptions } from '../api/ws';
import type { DashboardSocket } from '../api/ws';
import type { RealtimeMessage } from '../api/types';

vi.mock('../auth/useAuth', () => ({
  useAuth: () => ({
    user: userFixture,
    loading: false,
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));

function ConnectedBadge() {
  const { connected } = useRealtime();
  return <div>{connected ? 'online' : 'offline'}</div>;
}

describe('RealtimeProvider', () => {
  it('connects while signed in and invalidates caches from notifications', () => {
    let captured: DashboardSocketOptions | null = null;
    const connect = vi.fn();
    const close = vi.fn();
    const createSocket = (options: DashboardSocketOptions) => {
      captured = options;
      return { connect, close } as unknown as DashboardSocket;
    };

    const queryClient = createTestQueryClient();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

    render(
      <TestProviders queryClient={queryClient}>
        <RealtimeProvider createSocket={createSocket}>
          <ConnectedBadge />
        </RealtimeProvider>
      </TestProviders>,
    );

    expect(connect).toHaveBeenCalledTimes(1);

    const message: RealtimeMessage = {
      type: 'event',
      event: {
        id: 1,
        event_id: '11111111-1111-1111-1111-111111111111',
        camera_id: 1,
        event_type: 'person_entering',
        status: 'completed',
        review_status: 'unreviewed',
        trigger_time: '2026-10-02T10:00:00Z',
        message: 'Person entered.',
      },
    };

    act(() => {
      captured?.onMessage?.(message);
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['events'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['event'] });

    // A reconnect refetches everything, recovering updates missed while offline.
    act(() => {
      captured?.onOpen?.();
    });
    expect(invalidate).toHaveBeenCalledWith();

    // Connection status is surfaced to the UI and gated on the session.
    act(() => {
      captured?.onStatusChange?.(true);
    });
    expect(screen.getByText('online')).toBeInTheDocument();
  });
});
