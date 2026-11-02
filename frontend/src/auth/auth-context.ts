import { createContext } from 'react';

import type { User } from '../api/types';

export interface AuthContextValue {
  user: User | null;
  /** True while the initial `/api/auth/me` probe is in flight. */
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
