import { useContext } from 'react';

import { RealtimeContext } from './realtime-context';
import type { RealtimeContextValue } from './realtime-context';

export function useRealtime(): RealtimeContextValue {
  return useContext(RealtimeContext);
}
