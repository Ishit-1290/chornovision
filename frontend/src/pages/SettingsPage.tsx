import { Link as RouterLink } from 'react-router-dom';
import {
  Alert,
  Card,
  CardContent,
  Grid,
  Link,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableRow,
  Typography,
} from '@mui/material';

import { useSettings } from '../hooks/queries';
import { ErrorState, LoadingState } from '../components/states';
import { formatBytes } from '../lib/format';

export function SettingsPage() {
  const settings = useSettings();

  if (settings.isLoading) return <LoadingState />;
  if (settings.isError)
    return <ErrorState error={settings.error} onRetry={() => settings.refetch()} />;
  if (!settings.data) return null;

  const data = settings.data;

  const rows: Array<[string, string]> = [
    ['Evidence capture', data.evidence_enabled ? 'Enabled' : 'Disabled'],
    ['Snapshots', data.evidence_snapshot_enabled ? 'Enabled' : 'Disabled'],
    ['Retention window', `${data.evidence_retention_days} days`],
    ['Storage cap', `${data.evidence_storage_limit_gb} GB`],
    ['Auto retention on register', data.evidence_retention_on_register ? 'Enabled' : 'Disabled'],
    ['Rolling buffer', `${data.evidence_rolling_buffer_seconds} s`],
    ['Pre-event window', `${data.evidence_pre_event_seconds} s`],
    ['Post-event window', `${data.evidence_post_event_seconds} s`],
    ['Clip frames per second', String(data.evidence_clip_fps)],
    ['Clip frame cap', String(data.evidence_clip_max_frames)],
    ['Worker heartbeat timeout', `${data.worker_heartbeat_timeout_seconds} s`],
    ['Evidence storage used', formatBytes(data.evidence_storage_used_bytes)],
  ];

  return (
    <Stack spacing={3}>
      <Typography variant="h1">Settings</Typography>

      <Alert severity="info">
        Retention and evidence policy are controlled by the backend environment and are shown
        read-only here. Deletion is an explicit operator action (
        <code>chronovision-admin prune-evidence</code>); the dashboard never changes policy or
        deletes evidence.
      </Alert>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card>
            <CardContent>
              <Typography variant="h3" sx={{ mb: 1 }}>
                Effective operational policy
              </Typography>
              <Table size="small">
                <TableBody>
                  {rows.map(([label, value]) => (
                    <TableRow key={label}>
                      <TableCell component="th" scope="row" sx={{ color: 'text.secondary' }}>
                        {label}
                      </TableCell>
                      <TableCell align="right">{value}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 6 }}>
          <Card>
            <CardContent>
              <Typography variant="h3" sx={{ mb: 1 }}>
                Per-camera configuration
              </Typography>
              <Typography color="text.secondary" gutterBottom>
                Camera zones and rule thresholds are validated by the backend and edited per camera.
                Open a camera and edit its JSON configuration; an invalid object is rejected with
                HTTP 422.
              </Typography>
              <Link component={RouterLink} to="/cameras">
                Go to cameras
              </Link>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Stack>
  );
}
