import { Link as RouterLink } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Grid,
  Link,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';

import {
  useCameras,
  useEvents,
  useHealth,
  useMonitoringCommands,
  useMonitoringStatus,
  useSettings,
} from '../hooks/queries';
import { CameraStatusChip, EventStatusChip, ReviewStatusChip } from '../components/chips';
import { EmptyState, ErrorState, LoadingState } from '../components/states';
import { formatDateTime } from '../lib/format';

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent>
        <Typography color="text.secondary" variant="overline">
          {label}
        </Typography>
        <Typography variant="h2" sx={{ mt: 1 }}>
          {value}
        </Typography>
        {hint !== undefined && (
          <Typography color="text.secondary" variant="body2" sx={{ mt: 0.5 }}>
            {hint}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}

export function OverviewPage() {
  const health = useHealth();
  const monitoring = useMonitoringStatus();
  const cameras = useCameras();
  const events = useEvents({ limit: 5 });
  const commands = useMonitoringCommands();
  const settings = useSettings();

  const activeCameras = cameras.data?.filter((camera) => camera.status === 'active').length ?? 0;
  const enabledCameras = cameras.data?.filter((camera) => camera.enabled).length ?? 0;

  const monitoringState = monitoring.data?.state ?? 'unknown';
  const busy = commands.start.isPending || commands.pause.isPending || commands.stop.isPending;
  const commandError = commands.start.error ?? commands.pause.error ?? commands.stop.error;

  return (
    <Stack spacing={3}>
      <Typography variant="h1">Overview</Typography>

      {health.isError && <ErrorState error={health.error} onRetry={() => health.refetch()} />}

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <StatCard
            label="System"
            value={health.isLoading ? '…' : (health.data?.status ?? 'unknown')}
            hint={health.data ? `env: ${health.data.environment}` : undefined}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <StatCard
            label="Monitoring"
            value={monitoring.isLoading ? '…' : monitoringState}
            hint="Start/pause/stop is always an explicit action"
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <StatCard
            label="Cameras"
            value={cameras.isLoading ? '…' : String(cameras.data?.length ?? 0)}
            hint={`${enabledCameras} enabled · ${activeCameras} active`}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <StatCard
            label="Events (recent)"
            value={events.isLoading ? '…' : String(events.data?.total ?? 0)}
            hint="Total matching the default filter"
          />
        </Grid>
      </Grid>

      <Card>
        <CardContent>
          <Stack direction="row" spacing={2} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
            <Typography variant="h3" sx={{ flexGrow: 1 }}>
              Monitoring control
            </Typography>
            <Button
              variant="contained"
              disabled={busy || monitoringState === 'running'}
              onClick={() => commands.start.mutate()}
            >
              Start
            </Button>
            <Button
              variant="outlined"
              disabled={busy || monitoringState !== 'running'}
              onClick={() => commands.pause.mutate()}
            >
              Pause
            </Button>
            <Button
              variant="outlined"
              color="warning"
              disabled={busy || monitoringState === 'stopped'}
              onClick={() => commands.stop.mutate()}
            >
              Stop
            </Button>
          </Stack>
          {commandError !== null && commandError !== undefined && (
            <Box sx={{ mt: 2 }}>
              <ErrorState error={commandError} />
            </Box>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack direction="row" sx={{ mb: 1, alignItems: 'center' }}>
            <Typography variant="h3" sx={{ flexGrow: 1 }}>
              Recent events
            </Typography>
            <Link component={RouterLink} to="/events">
              View all
            </Link>
          </Stack>

          {events.isLoading && <LoadingState />}
          {events.isError && <ErrorState error={events.error} onRetry={() => events.refetch()} />}
          {events.data && events.data.items.length === 0 && (
            <EmptyState>No events have been recorded yet.</EmptyState>
          )}
          {events.data && events.data.items.length > 0 && (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Time</TableCell>
                  <TableCell>Camera</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Review</TableCell>
                  <TableCell>Message</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {events.data.items.map((event) => (
                  <TableRow key={event.id} hover>
                    <TableCell>{formatDateTime(event.trigger_time)}</TableCell>
                    <TableCell>{event.camera_id}</TableCell>
                    <TableCell>
                      <EventStatusChip status={event.status} />
                    </TableCell>
                    <TableCell>
                      <ReviewStatusChip status={event.review_status} />
                    </TableCell>
                    <TableCell>
                      <Link component={RouterLink} to={`/events/${event.id}`}>
                        {event.message}
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="h3" sx={{ mb: 1 }}>
            Cameras
          </Typography>
          {cameras.isLoading && <LoadingState />}
          {cameras.isError && (
            <ErrorState error={cameras.error} onRetry={() => cameras.refetch()} />
          )}
          {cameras.data && cameras.data.length === 0 && (
            <EmptyState>
              No cameras configured.{' '}
              <Link component={RouterLink} to="/cameras">
                Add one
              </Link>
              .
            </EmptyState>
          )}
          {cameras.data && cameras.data.length > 0 && (
            <Stack spacing={1}>
              {cameras.data.map((camera) => (
                <Stack key={camera.id} direction="row" spacing={2} sx={{ alignItems: 'center' }}>
                  <CameraStatusChip status={camera.status} />
                  <Typography sx={{ flexGrow: 1 }}>{camera.name}</Typography>
                  <Typography color="text.secondary" variant="body2">
                    {camera.stream_reference}
                  </Typography>
                </Stack>
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>

      {settings.data?.live_playback_enabled === true ? (
        <Alert
          severity="success"
          action={
            <Button component={RouterLink} to="/cameras" color="inherit" size="small">
              Open cameras
            </Button>
          }
        >
          Live playback is enabled. Open a camera and choose “Live” to start a WebRTC stream. Stored
          snapshots and clips remain available in the event timeline.
        </Alert>
      ) : (
        !settings.isLoading && (
          <Alert severity="info">
            Live video playback is not available: no streaming gateway (e.g. MediaMTX/WebRTC) is
            configured. Only stored snapshot and clip evidence can be reviewed. See{' '}
            <code>docs/LIVE_PLAYBACK.md</code> to enable it.
          </Alert>
        )
      )}
    </Stack>
  );
}
