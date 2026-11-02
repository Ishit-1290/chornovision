import { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import {
  AppBar,
  Box,
  Button,
  Chip,
  Container,
  IconButton,
  Menu,
  MenuItem,
  Toolbar,
  Tooltip,
  Typography,
} from '@mui/material';
import VideocamIcon from '@mui/icons-material/Videocam';
import PersonIcon from '@mui/icons-material/Person';

import { useAuth } from '../auth/useAuth';
import { useRealtime } from '../realtime/useRealtime';

const NAV_ITEMS = [
  { to: '/', label: 'Overview', end: true },
  { to: '/cameras', label: 'Cameras' },
  { to: '/events', label: 'Events' },
  { to: '/settings', label: 'Settings' },
];

export function AppLayout() {
  const { user, logout } = useAuth();
  const { connected } = useRealtime();
  const navigate = useNavigate();
  const [anchor, setAnchor] = useState<null | HTMLElement>(null);

  const handleLogout = async () => {
    setAnchor(null);
    await logout();
    navigate('/login', { replace: true });
  };

  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <AppBar position="static" elevation={0} color="default">
        <Toolbar sx={{ gap: 2 }}>
          <VideocamIcon color="primary" />
          <Typography variant="h3" sx={{ mr: 2 }}>
            ChronoVision
          </Typography>

          <Box sx={{ display: 'flex', gap: 1, flexGrow: 1 }}>
            {NAV_ITEMS.map((item) => (
              <Button
                key={item.to}
                component={NavLink}
                to={item.to}
                end={item.end}
                color="inherit"
                sx={{
                  '&.active': { color: 'primary.main', backgroundColor: 'action.selected' },
                }}
              >
                {item.label}
              </Button>
            ))}
          </Box>

          <Tooltip title={connected ? 'Live updates connected' : 'Live updates disconnected'}>
            <Chip
              size="small"
              label={connected ? 'Live' : 'Offline'}
              color={connected ? 'success' : 'default'}
              variant={connected ? 'filled' : 'outlined'}
            />
          </Tooltip>

          <Tooltip title={user?.username ?? ''}>
            <IconButton color="inherit" onClick={(event) => setAnchor(event.currentTarget)}>
              <PersonIcon />
            </IconButton>
          </Tooltip>
          <Menu anchorEl={anchor} open={anchor !== null} onClose={() => setAnchor(null)}>
            <MenuItem disabled>{user?.username}</MenuItem>
            <MenuItem onClick={handleLogout}>Sign out</MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>

      <Container maxWidth="xl" sx={{ py: 3, flexGrow: 1 }}>
        <Outlet />
      </Container>
    </Box>
  );
}
