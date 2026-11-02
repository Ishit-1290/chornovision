import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { DashboardSocket } from '../api/ws';
import type { DashboardSocketOptions } from '../api/ws';
import type { RealtimeMessage } from '../api/types';
import { useAuth } from '../auth/useAuth';
import { RealtimeContext } from './realtime-context';
import type { RealtimeContextValue } from './realtime-context';

type SocketFactory = (options: DashboardSocketOptions) => DashboardSocket;

export interface RealtimeProviderProps {
  children: ReactNode;
  /** Injectable for tests; defaults to the real browser-backed socket. */
  createSocket?: SocketFactory;
}

/**
 * Connects the dashboard to `/api/ws` while a session is active and uses the lightweight
 * notifications only to *invalidate* React Query caches. The REST API stays the source of
 * truth, so a reconnect simply refetches — that is how updates missed while the socket was
 * down are recovered.
 */
export function RealtimeProvider({ children, createSocket }: RealtimeProviderProps) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [socketConnected, setSocketConnected] = useState(false);
  const socketRef = useRef<DashboardSocket | null>(null);

  useEffect(() => {
    if (user === null) return;

    const handleMessage = (message: RealtimeMessage) => {
      switch (message.type) {
        case 'event':
          void queryClient.invalidateQueries({ queryKey: ['events'] });
          void queryClient.invalidateQueries({ queryKey: ['event'] });
          break;
        case 'camera':
          void queryClient.invalidateQueries({ queryKey: ['cameras'] });
          void queryClient.invalidateQueries({ queryKey: ['monitoring'] });
          void queryClient.invalidateQueries({ queryKey: ['camera-health'] });
          break;
        case 'monitoring':
          void queryClient.invalidateQueries({ queryKey: ['monitoring'] });
          void queryClient.invalidateQueries({ queryKey: ['cameras'] });
          void queryClient.invalidateQueries({ queryKey: ['events'] });
          break;
        case 'evidence':
          void queryClient.invalidateQueries({ queryKey: ['event', message.event_id] });
          break;
        default:
          break;
      }
    };

    const factory: SocketFactory = createSocket ?? ((options) => new DashboardSocket(options));
    const socket = factory({
      onMessage: handleMessage,
      // Every (re)connection refetches everything: missed-update recovery.
      onOpen: () => {
        void queryClient.invalidateQueries();
      },
      onStatusChange: setSocketConnected,
    });
    socketRef.current = socket;
    socket.connect();

    return () => {
      socket.close();
      socketRef.current = null;
    };
  }, [user, queryClient, createSocket]);

  const value = useMemo<RealtimeContextValue>(
    () => ({ connected: user !== null && socketConnected }),
    [user, socketConnected],
  );

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>;
}
