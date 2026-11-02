import { useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

import {
  useCameraMutations,
  useCameras,
  useMonitoringCommands,
  useMonitoringStatus,
} from '../hooks/queries';
import { CameraStatusChip } from '../components/chips';
import { LivePlaybackDialog } from '../components/LivePlaybackDialog';
import { ZoneSetupWizard } from '../wizard/ZoneSetupWizard';
import { EmptyState, ErrorState, LoadingState } from '../components/states';
import type { Camera } from '../api/types';
import { ApiError } from '../api/client';
import { formatDateTime } from '../lib/format';

interface CameraFormState {
  id: number | null;
  name: string;
  streamReference: string;
  enabled: boolean;
  configuration: string;
  streamUsername: string;
  streamPassword: string;
  hasCredentials: boolean;
  clearCredentials: boolean;
}

const EMPTY_FORM: CameraFormState = {
  id: null,
  name: '',
  streamReference: '',
  enabled: true,
  configuration: '{}',
  streamUsername: '',
  streamPassword: '',
  hasCredentials: false,
  clearCredentials: false,
};

function toForm(camera: Camera): CameraFormState {
  return {
    id: camera.id,
    name: camera.name,
    // The API only returns a redacted reference; leave the field blank so we never echo it
    // back as if it were the real stream URL. A blank value means "leave unchanged".
    streamReference: '',
    enabled: camera.enabled,
    configuration: JSON.stringify(camera.configuration ?? {}, null, 2),
    streamUsername: '',
    streamPassword: '',
    hasCredentials: camera.has_stream_credentials,
    clearCredentials: false,
  };
}

export function CamerasPage() {
  const cameras = useCameras();
  const monitoring = useMonitoringStatus();
  const commands = useMonitoringCommands();
  const mutations = useCameraMutations();

  const [form, setForm] = useState<CameraFormState | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [liveCamera, setLiveCamera] = useState<Camera | null>(null);
  const [wizardCamera, setWizardCamera] = useState<Camera | null>(null);

  const openCreate = () => {
    setFormError(null);
    setForm({ ...EMPTY_FORM });
  };

  const openEdit = (camera: Camera) => {
    setFormError(null);
    setForm(toForm(camera));
  };

  const editing = form?.id !== null && form !== null;

  const submit = async () => {
    if (form === null) return;
    setFormError(null);

    let configuration: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(form.configuration || '{}');
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Configuration must be a JSON object.');
      }
      configuration = parsed as Record<string, unknown>;
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Invalid JSON configuration.');
      return;
    }

    const hasUsername = form.streamUsername.length > 0;
    const hasPassword = form.streamPassword.length > 0;
    if (hasUsername !== hasPassword) {
      setFormError('Stream username and password must be provided together.');
      return;
    }
    if (form.clearCredentials && hasUsername) {
      setFormError('Clear the stored credentials or enter a new pair, not both.');
      return;
    }
    const credentials = hasUsername
      ? { stream_username: form.streamUsername, stream_password: form.streamPassword }
      : {};

    try {
      if (form.id === null) {
        if (!form.streamReference.trim()) {
          setFormError('A stream reference is required.');
          return;
        }
        await mutations.create.mutateAsync({
          name: form.name.trim(),
          stream_reference: form.streamReference.trim(),
          enabled: form.enabled,
          configuration,
          ...credentials,
        });
      } else {
        await mutations.update.mutateAsync({
          id: form.id,
          payload: {
            name: form.name.trim(),
            enabled: form.enabled,
            configuration,
            ...(form.streamReference.trim()
              ? { stream_reference: form.streamReference.trim() }
              : {}),
            ...credentials,
            ...(form.clearCredentials ? { clear_stream_credentials: true } : {}),
          },
        });
      }
      setForm(null);
    } catch (caught) {
      setFormError(
        caught instanceof ApiError
          ? `${caught.message} (HTTP ${caught.status})`
          : caught instanceof Error
            ? caught.message
            : 'Unexpected error',
      );
    }
  };

  const toggleEnabled = (camera: Camera) => {
    mutations.update.mutate({ id: camera.id, payload: { enabled: !camera.enabled } });
  };

  const monitoringState = monitoring.data?.state ?? 'unknown';
  const busy = commands.start.isPending || commands.pause.isPending || commands.stop.isPending;

  return (
    <Stack spacing={3}>
      <Stack direction="row" sx={{ alignItems: 'center' }}>
        <Typography variant="h1" sx={{ flexGrow: 1 }}>
          Cameras
        </Typography>
        <Button variant="contained" onClick={openCreate}>
          Add camera
        </Button>
      </Stack>

      <Card>
        <CardContent>
          <Stack direction="row" spacing={2} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
            <Typography variant="h3" sx={{ flexGrow: 1 }}>
              Monitoring: {monitoringState}
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
        </CardContent>
      </Card>

      {(mutations.create.isError || mutations.update.isError) && (
        <ErrorState error={mutations.create.error ?? mutations.update.error} />
      )}

      <Card>
        <CardContent>
          {cameras.isLoading && <LoadingState />}
          {cameras.isError && (
            <ErrorState error={cameras.error} onRetry={() => cameras.refetch()} />
          )}
          {cameras.data && cameras.data.length === 0 && (
            <EmptyState>No cameras yet. Add one to begin.</EmptyState>
          )}
          {cameras.data && cameras.data.length > 0 && (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Name</TableCell>
                  <TableCell>Stream (redacted)</TableCell>
                  <TableCell>Credentials</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Enabled</TableCell>
                  <TableCell>Updated</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {cameras.data.map((camera) => (
                  <TableRow key={camera.id} hover>
                    <TableCell>{camera.name}</TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {camera.stream_reference}
                      </Typography>
                    </TableCell>
                    <TableCell>{camera.has_stream_credentials ? 'Configured' : '—'}</TableCell>
                    <TableCell>
                      <CameraStatusChip status={camera.status} />
                    </TableCell>
                    <TableCell>{camera.enabled ? 'Yes' : 'No'}</TableCell>
                    <TableCell>{formatDateTime(camera.updated_at)}</TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={1} sx={{ justifyContent: 'flex-end' }}>
                        <Button size="small" onClick={() => setLiveCamera(camera)}>
                          Live
                        </Button>
                        <Button size="small" onClick={() => setWizardCamera(camera)}>
                          Zones &amp; events
                        </Button>
                        <Button size="small" onClick={() => openEdit(camera)}>
                          Edit
                        </Button>
                        <Button
                          size="small"
                          color={camera.enabled ? 'warning' : 'success'}
                          onClick={() => toggleEnabled(camera)}
                        >
                          {camera.enabled ? 'Disable' : 'Enable'}
                        </Button>
                      </Stack>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={form !== null} onClose={() => setForm(null)} fullWidth maxWidth="md">
        <DialogTitle>{editing ? 'Edit camera' : 'Add camera'}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {formError !== null && <Alert severity="error">{formError}</Alert>}
            {form !== null && (
              <>
                <TextField
                  label="Name"
                  value={form.name}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
                  required
                  fullWidth
                />
                <TextField
                  label={
                    editing ? 'Stream reference (leave blank to keep current)' : 'Stream reference'
                  }
                  value={form.streamReference}
                  onChange={(event) => setForm({ ...form, streamReference: event.target.value })}
                  helperText="Example: rtsp://host:554/stream. Credentials are never displayed."
                  fullWidth
                />
                <Typography variant="subtitle2">Stream credentials (optional)</Typography>
                <TextField
                  label="Stream username"
                  value={form.streamUsername}
                  onChange={(event) => setForm({ ...form, streamUsername: event.target.value })}
                  helperText={
                    form.hasCredentials
                      ? 'Credentials are stored encrypted and never displayed. Enter a new username and password to replace them.'
                      : 'Only needed when the camera requires authentication.'
                  }
                  autoComplete="off"
                  fullWidth
                />
                <TextField
                  label="Stream password"
                  type="password"
                  value={form.streamPassword}
                  onChange={(event) => setForm({ ...form, streamPassword: event.target.value })}
                  helperText="Sent only to the backend and encrypted at rest; never returned to the browser."
                  autoComplete="new-password"
                  fullWidth
                />
                {editing && form.hasCredentials && (
                  <FormControlLabel
                    control={
                      <Switch
                        checked={form.clearCredentials}
                        onChange={(event) =>
                          setForm({
                            ...form,
                            clearCredentials: event.target.checked,
                            streamUsername: event.target.checked ? '' : form.streamUsername,
                            streamPassword: event.target.checked ? '' : form.streamPassword,
                          })
                        }
                      />
                    }
                    label="Clear stored credentials"
                  />
                )}
                <FormControlLabel
                  control={
                    <Switch
                      checked={form.enabled}
                      onChange={(event) => setForm({ ...form, enabled: event.target.checked })}
                    />
                  }
                  label="Enabled"
                />
                <Accordion disableGutters>
                  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Typography variant="body2">Advanced: configuration (JSON)</Typography>
                  </AccordionSummary>
                  <AccordionDetails>
                    <Stack spacing={1}>
                      <TextField
                        label="Configuration (JSON)"
                        value={form.configuration}
                        onChange={(event) =>
                          setForm({ ...form, configuration: event.target.value })
                        }
                        multiline
                        minRows={8}
                        fullWidth
                        slotProps={{ input: { sx: { fontFamily: 'monospace', fontSize: 13 } } }}
                      />
                      <Typography color="text.secondary" variant="body2">
                        Zones and thresholds are validated by the backend; an invalid object is
                        rejected with HTTP 422. Prefer the “Zones &amp; events” wizard for normal
                        setup.
                      </Typography>
                    </Stack>
                  </AccordionDetails>
                </Accordion>
              </>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setForm(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={submit}
            disabled={mutations.create.isPending || mutations.update.isPending}
          >
            {editing ? 'Save' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      <LivePlaybackDialog
        key={liveCamera?.id ?? 'none'}
        camera={liveCamera}
        onClose={() => setLiveCamera(null)}
      />
      <ZoneSetupWizard
        key={wizardCamera?.id ?? 'none'}
        camera={wizardCamera}
        onClose={() => setWizardCamera(null)}
      />
    </Stack>
  );
}
