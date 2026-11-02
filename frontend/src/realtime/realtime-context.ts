import { createContext } from 'react';

export interface RealtimeContextValue {
  /** Whether the notification socket is currently open for the signed-in user. */
  connected: boolean;
}

export const RealtimeContext = createContext<RealtimeContextValue>({ connected: false });
