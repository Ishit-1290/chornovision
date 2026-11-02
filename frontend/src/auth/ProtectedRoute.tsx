import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { useAuth } from './useAuth';

/**
 * Gate for authenticated routes. While the initial session probe runs we render nothing
 * rather than flashing the login screen; unauthenticated users are redirected (preserving
 * their intended destination) instead of seeing any protected content.
 */
export function ProtectedRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return null;

  if (user === null) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <Outlet />;
}
