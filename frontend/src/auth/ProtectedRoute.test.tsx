import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';

import { AuthProvider } from './AuthContext';
import { ProtectedRoute } from './ProtectedRoute';
import { ApiError } from '../api/client';
import { renderWithProviders } from '../test/render';
import { userFixture } from '../test/fixtures';
import * as authApi from '../api/auth';

vi.mock('../api/auth', () => ({
  me: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}));

function renderProtected() {
  return renderWithProviders(
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<div>Login Screen</div>} />
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<div>Secret Content</div>} />
        </Route>
      </Routes>
    </AuthProvider>,
    { route: '/' },
  );
}

describe('ProtectedRoute', () => {
  it('redirects unauthenticated visitors to the login page', async () => {
    vi.mocked(authApi.me).mockRejectedValue(new ApiError(401, 'Not authenticated'));
    renderProtected();
    expect(await screen.findByText('Login Screen')).toBeInTheDocument();
    expect(screen.queryByText('Secret Content')).not.toBeInTheDocument();
  });

  it('renders protected content for an authenticated user', async () => {
    vi.mocked(authApi.me).mockResolvedValue(userFixture);
    renderProtected();
    expect(await screen.findByText('Secret Content')).toBeInTheDocument();
  });
});
