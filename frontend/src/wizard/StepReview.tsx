import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Chip,
  Divider,
  Stack,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

import { EVENT_DEFINITIONS, KIND_LABELS } from './eventCatalog';
import { thresholdsForEvents } from './thresholdCatalog';
import type { CameraConfiguration, WizardValidation } from './convert';
import type { EventKey, ThresholdValues, WizardZone } from './wizardTypes';

export interface StepReviewProps {
  events: Record<EventKey, boolean>;
  zones: WizardZone[];
  thresholds: ThresholdValues;
  validation: WizardValidation;
  config: CameraConfiguration;
}

/**
 * Step 4 — review the configuration in plain language before saving, with an optional
 * collapsible Advanced JSON view for debugging (never the primary workflow).
 */
export function StepReview({ events, zones, thresholds, validation, config }: StepReviewProps) {
  const selected = EVENT_DEFINITIONS.filter((definition) => events[definition.key]);
  const definitions = thresholdsForEvents(events);
  const unsupported = EVENT_DEFINITIONS.filter((definition) => !definition.available);

  return (
    <Stack spacing={2}>
      {!validation.valid && (
        <Alert severity="error">
          Fix the following before saving:
          <ul style={{ margin: '0.25rem 0 0 1rem' }}>
            {[...validation.errors, ...Object.values(validation.zoneErrors).flat()].map(
              (message, index) => (
                <li key={index}>{message}</li>
              ),
            )}
          </ul>
        </Alert>
      )}

      <div>
        <Typography variant="h3">Events</Typography>
        {selected.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No events selected.
          </Typography>
        ) : (
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1, mt: 0.5 }}>
            {selected.map((definition) => (
              <Chip
                key={definition.key}
                label={definition.label}
                color="primary"
                variant="outlined"
              />
            ))}
          </Stack>
        )}
      </div>

      <div>
        <Typography variant="h3">Zones</Typography>
        {zones.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No zones defined.
          </Typography>
        ) : (
          <Stack spacing={0.5} sx={{ mt: 0.5 }}>
            {zones.map((zone) => (
              <Typography key={zone.id} variant="body2">
                <strong>{zone.name}</strong> — {KIND_LABELS[zone.kind]} ({zone.polygon.length}{' '}
                points)
                {zone.boundary !== null && (
                  <>
                    {' '}
                    · boundary direction: interior on the{' '}
                    <strong>{zone.boundary.inside_side}</strong> of point 1 → point 2
                  </>
                )}
              </Typography>
            ))}
          </Stack>
        )}
      </div>

      <div>
        <Typography variant="h3">Settings</Typography>
        {definitions.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No adjustable settings.
          </Typography>
        ) : (
          <Stack spacing={0.5} sx={{ mt: 0.5 }}>
            {definitions.map((definition) => (
              <Typography key={definition.key} variant="body2">
                {definition.label}:{' '}
                <strong>{thresholds[definition.key] ?? definition.defaultValue}</strong>{' '}
                {definition.unit}
              </Typography>
            ))}
          </Stack>
        )}
      </div>

      {unsupported.length > 0 && (
        <Alert severity="info">
          Not available yet on this deployment:{' '}
          {unsupported.map((definition) => definition.label).join(', ')}. These require inputs the
          vision worker does not yet provide.
        </Alert>
      )}

      <Divider />
      <Accordion disableGutters>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="body2">Advanced JSON (debugging)</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Typography variant="caption" color="text.secondary">
            This is the exact configuration that will be saved. Editing the JSON field directly is
            not required.
          </Typography>
          <pre data-testid="advanced-json" style={{ overflowX: 'auto', fontSize: 12 }}>
            {JSON.stringify(config, null, 2)}
          </pre>
        </AccordionDetails>
      </Accordion>
    </Stack>
  );
}
