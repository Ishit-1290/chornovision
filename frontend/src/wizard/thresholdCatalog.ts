/**
 * Friendly descriptions for the event-rule thresholds, grounded in the backend
 * `EventThresholds` schema (`backend/app/events/zones.py`) and its documented defaults.
 *
 * Only settings relevant to the currently selected events are shown. Each control carries a
 * unit, an input range, and validation, so users never have to know the raw threshold keys.
 */

import type { EventKey, ThresholdKey } from './wizardTypes';

export interface ThresholdDefinition {
  key: ThresholdKey;
  label: string;
  help: string;
  unit: string;
  min: number;
  max?: number;
  step: number;
  integer?: boolean;
  /** Which events make this setting relevant. */
  events: EventKey[];
  /** Default proposed by the backend schema. */
  defaultValue: number;
}

export const THRESHOLD_DEFINITIONS: ThresholdDefinition[] = [
  {
    key: 'boundary_confirm_frames',
    label: 'Crossing confirmation',
    help: 'How many consecutive frames a crossing must be seen before an entrance/exit event is raised.',
    unit: 'frames',
    min: 1,
    max: 60,
    step: 1,
    integer: true,
    events: ['person_entering', 'person_leaving'],
    defaultValue: 2,
  },
  {
    key: 'boundary_cooldown_seconds',
    label: 'Crossing cooldown',
    help: 'Ignore repeat crossings of the same boundary for this long, to avoid duplicates.',
    unit: 'seconds',
    min: 0,
    step: 0.5,
    events: ['person_entering', 'person_leaving'],
    defaultValue: 2,
  },
  {
    key: 'occupancy_persistence_seconds',
    label: 'Occupancy persistence',
    help: 'How long an occupancy change must hold before it is reported.',
    unit: 'seconds',
    min: 0,
    step: 0.5,
    events: ['room_occupancy_change'],
    defaultValue: 2,
  },
  {
    key: 'occupancy_retention_seconds',
    label: 'Occupancy retention',
    help: 'How long a person is kept in the count after briefly leaving view inside the room.',
    unit: 'seconds',
    min: 0.1,
    step: 0.5,
    events: ['room_occupancy_change'],
    defaultValue: 3,
  },
  {
    key: 'crowd_occupancy_threshold',
    label: 'Crowd size',
    help: 'Number of people at or above which the area counts as a crowd.',
    unit: 'people',
    min: 1,
    step: 1,
    integer: true,
    events: ['crowd_forming'],
    defaultValue: 3,
  },
  {
    key: 'crowd_persistence_seconds',
    label: 'Crowd persistence',
    help: 'How long the crowd size must hold before a crowd event is raised.',
    unit: 'seconds',
    min: 0,
    step: 1,
    events: ['crowd_forming'],
    defaultValue: 15,
  },
  {
    key: 'crowd_release_seconds',
    label: 'Crowd release time',
    help: 'How long the count must stay below the threshold before the crowd event completes.',
    unit: 'seconds',
    min: 0,
    step: 1,
    events: ['crowd_forming'],
    defaultValue: 5,
  },
  {
    key: 'motionless_duration_seconds',
    label: 'Motionless duration',
    help: 'How long a person must barely move before a motionless event is raised.',
    unit: 'seconds',
    min: 0.1,
    step: 5,
    events: ['person_motionless'],
    defaultValue: 120,
  },
  {
    key: 'motionless_movement_threshold',
    label: 'Movement threshold',
    help: 'Per-frame movement (as a fraction of frame size) considered “no movement”.',
    unit: 'fraction of frame',
    min: 0,
    max: 1,
    step: 0.005,
    events: ['person_motionless'],
    defaultValue: 0.01,
  },
  {
    key: 'motionless_min_observations',
    label: 'Minimum observations',
    help: 'Minimum number of frames a person must be tracked before motionlessness counts.',
    unit: 'frames',
    min: 1,
    step: 1,
    integer: true,
    events: ['person_motionless'],
    defaultValue: 5,
  },
  {
    key: 'package_stationary_seconds',
    label: 'Stationary duration',
    help: 'How long a package must stay still before it counts as left behind.',
    unit: 'seconds',
    min: 0.1,
    step: 5,
    events: ['package_left_at_entrance'],
    defaultValue: 45,
  },
  {
    key: 'package_person_proximity',
    label: 'Person proximity',
    help: 'How close a person must be (fraction of frame size) for the package to be marked possible-unattended.',
    unit: 'fraction of frame',
    min: 0,
    max: 1,
    step: 0.01,
    events: ['package_left_at_entrance'],
    defaultValue: 0.15,
  },
];

export const THRESHOLD_BY_KEY: Record<ThresholdKey, ThresholdDefinition> = Object.fromEntries(
  THRESHOLD_DEFINITIONS.map((definition) => [definition.key, definition]),
) as Record<ThresholdKey, ThresholdDefinition>;

/** Thresholds relevant to the given event selection, in catalogue order. */
export function thresholdsForEvents(events: Record<EventKey, boolean>): ThresholdDefinition[] {
  return THRESHOLD_DEFINITIONS.filter((definition) =>
    definition.events.some((event) => events[event]),
  );
}

/** All default values, used to seed the wizard from a camera with no saved thresholds. */
export function defaultThresholds(): Record<ThresholdKey, number> {
  return Object.fromEntries(
    THRESHOLD_DEFINITIONS.map((definition) => [definition.key, definition.defaultValue]),
  ) as Record<ThresholdKey, number>;
}
