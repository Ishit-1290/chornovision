import { Stack, TextField, Typography } from '@mui/material';

import { thresholdsForEvents } from './thresholdCatalog';
import type { EventKey, ThresholdKey, ThresholdValues } from './wizardTypes';

export interface StepThresholdsProps {
  events: Record<EventKey, boolean>;
  thresholds: ThresholdValues;
  onChange: (key: ThresholdKey, value: number) => void;
}

/**
 * Step 3 — friendly controls for the event-rule thresholds relevant to the selected events.
 * Unrelated saved thresholds are never touched.
 */
export function StepThresholds({ events, thresholds, onChange }: StepThresholdsProps) {
  const definitions = thresholdsForEvents(events);

  if (definitions.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No adjustable settings for the selected events.
      </Typography>
    );
  }

  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">
        Sensible defaults are pre-filled. Adjust only if you need to.
      </Typography>
      <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 2 }}>
        {definitions.map((definition) => {
          const value = thresholds[definition.key] ?? definition.defaultValue;
          const outOfRange =
            !Number.isFinite(value) ||
            value < definition.min ||
            (definition.max !== undefined && value > definition.max);
          return (
            <TextField
              key={definition.key}
              type="number"
              size="small"
              label={definition.label}
              value={Number.isFinite(value) ? value : ''}
              onChange={(event) => onChange(definition.key, Number(event.target.value))}
              error={outOfRange}
              helperText={
                outOfRange
                  ? `Enter a value between ${definition.min}${definition.max !== undefined ? ` and ${definition.max}` : ''}.`
                  : `${definition.help} (${definition.unit})`
              }
              slotProps={{
                htmlInput: {
                  min: definition.min,
                  max: definition.max,
                  step: definition.step,
                  'aria-label': definition.label,
                },
                inputLabel: { shrink: true },
              }}
              sx={{ width: 240 }}
            />
          );
        })}
      </Stack>
    </Stack>
  );
}
