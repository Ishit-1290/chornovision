import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import { AuthProvider } from '../auth/AuthContext';
import { LoginPage } from './LoginPage';
import { ApiError } from '../api/client';
import { renderWithProviders } from '../test/render';
import { userFixture } from '../test/fixtures';
import * as authApi from '../api/auth';

vi.mock('../api/auth', () => ({
  me: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}));

function renderLogin() {
  return renderWithProviders(
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div>Home Screen</div>} />
      </Routes>
    </AuthProvider>,
    { route: '/login' },
  );
}

describe('LoginPage', () => {
  it('submits credentials and navigates on success', async () => {
    vi.mocked(authApi.me).mockRejectedValue(new ApiError(401, 'Not authenticated'));
    vi.mocked(authApi.login).mockResolvedValue({
      user: userFixture,
      expires_at: '2026-10-09T00:00:00Z',
    });

    const user = userEvent.setup();
    renderLogin();

    await user.type(await screen.findByLabelText(/Username/), 'admin');
    await user.type(screen.getByLabelText(/Password/), 'secret');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(authApi.login).toHaveBeenCalledWith('admin', 'secret');
    expect(await screen.findByText('Home Screen')).toBeInTheDocument();
  });

  it('shows an error when credentials are rejected', async () => {
    vi.mocked(authApi.me).mockRejectedValue(new ApiError(401, 'Not authenticated'));
    vi.mocked(authApi.login).mockRejectedValue(new ApiError(401, 'Invalid credentials'));

    const user = userEvent.setup();
    renderLogin();

    await user.type(await screen.findByLabelText(/Username/), 'admin');
    await user.type(screen.getByLabelText(/Password/), 'wrong');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('Invalid username or password.')).toBeInTheDocument();
    expect(screen.queryByText('Home Screen')).not.toBeInTheDocument();
  });
});
