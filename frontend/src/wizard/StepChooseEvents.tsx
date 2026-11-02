import { Checkbox, Chip, FormControlLabel, Stack, Typography } from '@mui/material';

import { EVENT_DEFINITIONS, ROLE_LABELS } from './eventCatalog';
import type { EventKey } from './wizardTypes';

export interface StepChooseEventsProps {
  events: Record<EventKey, boolean>;
  onToggle: (key: EventKey, enabled: boolean) => void;
}

/**
 * Step 1 — choose which events to detect.
 *
 * Options reflect the real implementation. Unsupported events are shown disabled and clearly
 * labelled "Not available yet" so they are never mistaken for working features.
 */
export function StepChooseEvents({ events, onToggle }: StepChooseEventsProps) {
  return (
    <Stack spacing={1.5}>
      <Typography variant="body2" color="text.secondary">
        Select the events to detect on this camera. Zones needed by an event are drawn in the next
        step.
      </Typography>
      {EVENT_DEFINITIONS.map((definition) => {
        const disabled = !definition.available || definition.alwaysOn === true;
        const checked = events[definition.key];
        return (
          <Stack key={definition.key} direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
            <FormControlLabel
              sx={{ alignItems: 'flex-start', mr: 0 }}
              control={
                <Checkbox
                  checked={checked}
                  disabled={disabled}
                  onChange={(event) => onToggle(definition.key, event.target.checked)}
                  slotProps={{ input: { 'aria-label': definition.label } }}
                />
              }
              label={
                <Stack spacing={0.25}>
                  <Stack
                    direction="row"
                    spacing={1}
                    sx={{ alignItems: 'center', flexWrap: 'wrap' }}
                  >
                    <Typography variant="subtitle2">{definition.label}</Typography>
                    {!definition.available && (
                      <Chip size="small" color="default" label="Not available yet" />
                    )}
                    {definition.alwaysOn === true && (
                      <Chip size="small" color="success" variant="outlined" label="Always active" />
                    )}
                    {definition.role !== null && (
                      <Chip
                        size="small"
                        variant="outlined"
                        label={`Needs: ${ROLE_LABELS[definition.role]} zone`}
                      />
                    )}
                  </Stack>
                  <Typography variant="body2" color="text.secondary">
                    {definition.description}
                  </Typography>
                  {definition.unavailableReason !== undefined && (
                    <Typography variant="caption" color="warning.main">
                      {definition.unavailableReason}
                    </Typography>
                  )}
                  {definition.note !== undefined && (
                    <Typography variant="caption" color="text.secondary">
                      {definition.note}
                    </Typography>
                  )}
                </Stack>
              }
            />
          </Stack>
        );
      })}
    </Stack>
  );
}
