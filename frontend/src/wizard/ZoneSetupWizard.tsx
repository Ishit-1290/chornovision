import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stepper,
  Step,
  StepLabel,
  Stack,
  Typography,
} from '@mui/material';

import type { Camera } from '../api/types';
import { ApiError } from '../api/client';
import { useCameraMutations, useMonitoringCommands, useMonitoringStatus } from '../hooks/queries';
import { configToWizard, validateWizard, wizardToConfig } from './convert';
import type { CameraConfiguration } from './convert';
import { requiredRoles } from './eventCatalog';
import { StepChooseEvents } from './StepChooseEvents';
import { ZoneEditor } from './ZoneEditor';
import { StepThresholds } from './StepThresholds';
import { StepReview } from './StepReview';
import { type EventKey, type ThresholdKey, type WizardState } from './wizardTypes';

const STEPS = ['Events', 'Zones', 'Settings', 'Review'];

export interface ZoneSetupWizardProps {
  camera: Camera | null;
  onClose: () => void;
}

/**
 * Zone & event setup wizard.
 *
 * Step 1 choose events · Step 2 draw zones over the preview · Step 3 adjust thresholds ·
 * Step 4 review and save. Saving uses the existing camera PATCH endpoint (auth + CSRF handled
 * by the API client) and preserves configuration the wizard does not own. The camera's worker
 * restarts automatically when its configuration changes while monitoring runs; starting
 * monitoring remains a separate, explicit action.
 */
export function ZoneSetupWizard({ camera, onClose }: ZoneSetupWizardProps) {
  const mutations = useCameraMutations();
  const monitoring = useMonitoringStatus();
  const commands = useMonitoringCommands();

  // State is initialised once per camera; the parent remounts the wizard via `key` when a
  // different camera is opened, so no effect is needed to reset it.
  const initialConfig = (camera?.configuration ?? {}) as CameraConfiguration;
  const [step, setStep] = useState(0);
  const [state, setState] = useState<WizardState>(() => configToWizard(initialConfig));
  const [original] = useState<CameraConfiguration>(initialConfig);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [phase, setPhase] = useState<'editing' | 'saving' | 'saved'>('editing');
  const [saveError, setSaveError] = useState<string | null>(null);

  const validation = useMemo(() => validateWizard(state), [state]);
  const config = useMemo(() => wizardToConfig(state, original), [state, original]);
  const roles = useMemo(() => requiredRoles(state.events), [state.events]);

  const monitoringState = monitoring.data?.state ?? 'unknown';
  const busy = commands.start.isPending || commands.pause.isPending || commands.stop.isPending;

  const toggleEvent = (key: EventKey, enabled: boolean) => {
    setState((current) => ({ ...current, events: { ...current.events, [key]: enabled } }));
  };

  const setThreshold = (key: ThresholdKey, value: number) => {
    setState((current) => ({ ...current, thresholds: { ...current.thresholds, [key]: value } }));
  };

  const save = async () => {
    if (camera === null) return;
    setSaveError(null);
    setPhase('saving');
    try {
      await mutations.update.mutateAsync({
        id: camera.id,
        payload: { configuration: config },
      });
      // Only report success once the API has confirmed the update.
      setPhase('saved');
    } catch (caught) {
      setPhase('editing');
      setSaveError(
        caught instanceof ApiError
          ? `${caught.message} (HTTP ${caught.status})`
          : caught instanceof Error
            ? caught.message
            : 'Unexpected error saving the configuration.',
      );
    }
  };

  const finish = () => {
    onClose();
  };

  return (
    <Dialog open={camera !== null} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>Zone &amp; event setup{camera !== null ? ` — ${camera.name}` : ''}</DialogTitle>
      <DialogContent dividers>
        {phase === 'saved' ? (
          <Stack spacing={2} sx={{ py: 2 }}>
            <Alert severity="success">
              Configuration saved. The camera&apos;s worker picks up the change automatically
              {monitoringState === 'running' ? ' (monitoring is running, so it will restart)' : ''}.
            </Alert>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
              <Typography variant="body2" color="text.secondary">
                Monitoring: {monitoringState}
              </Typography>
              <Button
                variant="contained"
                disabled={busy || monitoringState === 'running'}
                onClick={() => commands.start.mutate()}
              >
                Start monitoring
              </Button>
            </Stack>
            {commands.start.isError && <Alert severity="error">Could not start monitoring.</Alert>}
            {commands.start.isSuccess && <Alert severity="info">Monitoring started.</Alert>}
          </Stack>
        ) : (
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Stepper activeStep={step} alternativeLabel>
              {STEPS.map((label) => (
                <Step key={label}>
                  <StepLabel>{label}</StepLabel>
                </Step>
              ))}
            </Stepper>

            {saveError !== null && <Alert severity="error">{saveError}</Alert>}

            {step === 0 && <StepChooseEvents events={state.events} onToggle={toggleEvent} />}

            {step === 1 && camera !== null && (
              <ZoneEditor
                cameraId={camera.id}
                zones={state.zones}
                requiredRoles={roles}
                selectedZoneId={selectedZoneId}
                zoneErrors={validation.zoneErrors}
                rotation={state.rotation}
                onRotate={(rotation) => setState((current) => ({ ...current, rotation }))}
                onChange={(zones) => setState((current) => ({ ...current, zones }))}
                onSelectZone={setSelectedZoneId}
              />
            )}

            {step === 2 && (
              <StepThresholds
                events={state.events}
                thresholds={state.thresholds}
                onChange={setThreshold}
              />
            )}

            {step === 3 && (
              <StepReview
                events={state.events}
                zones={state.zones}
                thresholds={state.thresholds}
                validation={validation}
                config={config}
              />
            )}

            {step === 3 && monitoringState === 'running' && (
              <Alert severity="info">
                Monitoring is running. Saving restarts this camera&apos;s worker so the new zones
                and rules take effect.
              </Alert>
            )}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        {phase === 'saved' ? (
          <Button variant="contained" onClick={finish}>
            Close
          </Button>
        ) : (
          <>
            <Button onClick={onClose} disabled={phase === 'saving'}>
              Cancel
            </Button>
            <Box sx={{ flexGrow: 1 }} />
            <Button
              disabled={step === 0 || phase === 'saving'}
              onClick={() => setStep((s) => s - 1)}
            >
              Back
            </Button>
            {step < STEPS.length - 1 ? (
              <Button variant="contained" onClick={() => setStep((s) => s + 1)}>
                Next
              </Button>
            ) : (
              <Button
                variant="contained"
                onClick={save}
                disabled={!validation.valid || phase === 'saving'}
              >
                {phase === 'saving' ? 'Saving…' : 'Save configuration'}
              </Button>
            )}
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
