/**
 * Human-facing catalogue of the events the wizard can configure, grounded in the actual
 * implementation (`vision/event_engine` + `backend/app/events/zones.py`).
 *
 * Availability is honest: the worker currently feeds only person/object tracks to the event
 * engine, so door-state and pose inputs do not exist yet. Those events are marked
 * `available: false` and are shown disabled rather than as working options.
 */

import type { EventKey, ZoneKind, ZoneRole } from './wizardTypes';

/** Zone kind each configuration role must reference (mirrors backend `_ROLE_KINDS`). */
export const ROLE_KINDS: Record<ZoneRole, ZoneKind[]> = {
  entrance_zone_id: ['entrance'],
  room_zone_id: ['room'],
  door_zone_id: ['door'],
  package_zone_id: ['entrance', 'package_area'],
  bed_zone_id: ['bed'],
  floor_zone_id: ['floor'],
};

export interface EventDefinition {
  key: EventKey;
  label: string;
  description: string;
  /** Configuration role this event needs; `null` when no zone is required. */
  role: ZoneRole | null;
  /** True when the event can actually fire with today's worker inputs. */
  available: boolean;
  /** Shown for disabled events. */
  unavailableReason?: string;
  /** Shown for available-but-conditional events. */
  note?: string;
  /** True when the rule is always active and cannot be switched off via configuration. */
  alwaysOn?: boolean;
}

export const EVENT_DEFINITIONS: EventDefinition[] = [
  {
    key: 'person_entering',
    label: 'Person entering',
    description: 'A person crosses the entrance boundary towards the monitored interior.',
    role: 'entrance_zone_id',
    available: true,
  },
  {
    key: 'person_leaving',
    label: 'Person leaving',
    description: 'A person crosses the entrance boundary outwards, away from the interior.',
    role: 'entrance_zone_id',
    available: true,
  },
  {
    key: 'room_occupancy_change',
    label: 'Room occupancy changes',
    description: 'The number of people inside the room zone changes.',
    role: 'room_zone_id',
    available: true,
  },
  {
    key: 'crowd_forming',
    label: 'Crowd forming',
    description: 'Occupancy stays at or above a threshold for a sustained period.',
    role: 'room_zone_id',
    available: true,
  },
  {
    key: 'person_motionless',
    label: 'Person remains motionless',
    description: 'A tracked person barely moves for a sustained period. Needs no zone.',
    role: null,
    available: true,
    alwaysOn: true,
    note: 'Always active; it needs no zone. Tune how long and how still below.',
  },
  {
    key: 'package_left_at_entrance',
    label: 'Package left behind',
    description: 'A package-like object stays stationary inside the entrance package area.',
    role: 'package_zone_id',
    available: true,
    note: 'Requires a detector configured to report package/parcel classes; a person-only detector will not produce it.',
  },
  {
    key: 'door_open_too_long',
    label: 'Door remains open too long',
    description: 'A door stays open beyond the configured time.',
    role: 'door_zone_id',
    available: false,
    unavailableReason: 'Not available yet — the vision worker does not provide door-state input.',
  },
  {
    key: 'fall_from_bed',
    label: 'Falling from bed',
    description: 'A potential bed-to-floor transition consistent with a fall.',
    role: 'bed_zone_id',
    available: false,
    unavailableReason: 'Not available yet — the vision worker does not provide pose/posture input.',
  },
];

export const EVENT_BY_KEY: Record<EventKey, EventDefinition> = Object.fromEntries(
  EVENT_DEFINITIONS.map((definition) => [definition.key, definition]),
) as Record<EventKey, EventDefinition>;

/** Roles that the wizard can create/manage zones for, in display order. */
export const ROLE_LABELS: Record<ZoneRole, string> = {
  entrance_zone_id: 'Entrance',
  room_zone_id: 'Room',
  door_zone_id: 'Door',
  package_zone_id: 'Package area',
  bed_zone_id: 'Bed',
  floor_zone_id: 'Floor',
};

/** Short human label for a zone kind. */
export const KIND_LABELS: Record<ZoneKind, string> = {
  entrance: 'Entrance',
  room: 'Room',
  door: 'Door',
  bed: 'Bed',
  floor: 'Floor',
  package_area: 'Package area',
  other: 'Other',
};

/**
 * Roles implied by the currently selected events. `person_entering` and `person_leaving`
 * share the entrance role; occupancy and crowd share the room role.
 */
export function requiredRoles(events: Record<EventKey, boolean>): ZoneRole[] {
  const roles = new Set<ZoneRole>();
  for (const definition of EVENT_DEFINITIONS) {
    if (definition.role !== null && events[definition.key]) {
      roles.add(definition.role);
    }
  }
  return [...roles];
}

/** True when at least one selected event makes use of `role`. */
export function roleIsRequired(events: Record<EventKey, boolean>, role: ZoneRole): boolean {
  return requiredRoles(events).includes(role);
}
