import { useState } from 'react';
import type { FormEvent } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Alert, Box, Button, Paper, Stack, TextField, Typography } from '@mui/material';
import VideocamIcon from '@mui/icons-material/Videocam';

import { useAuth } from '../auth/useAuth';
import { ApiError } from '../api/client';
import { formatErrorText } from '../lib/errors';

interface LocationState {
  from?: string;
}

export function LoginPage() {
  const { user, loading, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (loading) return null;

  if (user !== null) {
    const target = (location.state as LocationState | null)?.from ?? '/';
    return <Navigate to={target} replace />;
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password);
      const target = (location.state as LocationState | null)?.from ?? '/';
      navigate(target, { replace: true });
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.status === 401
            ? 'Invalid username or password.'
            : formatErrorText(caught)
          : 'Sign-in failed. Please try again.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        p: 2,
      }}
    >
      <Paper sx={{ p: 4, width: '100%', maxWidth: 380 }}>
        <Stack spacing={3} sx={{ alignItems: 'center' }}>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
            <VideocamIcon color="primary" fontSize="large" />
            <Typography variant="h2">ChronoVision</Typography>
          </Stack>
          <Typography color="text.secondary" align="center">
            Sign in to the monitoring dashboard.
          </Typography>

          {error !== null && <Alert severity="error">{error}</Alert>}

          <Box component="form" onSubmit={handleSubmit} sx={{ width: '100%' }}>
            <Stack spacing={2}>
              <TextField
                label="Username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                autoFocus
                required
                fullWidth
              />
              <TextField
                label="Password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
                fullWidth
              />
              <Button type="submit" variant="contained" disabled={submitting} fullWidth>
                {submitting ? 'Signing in…' : 'Sign in'}
              </Button>
            </Stack>
          </Box>
        </Stack>
      </Paper>
    </Box>
  );
}
