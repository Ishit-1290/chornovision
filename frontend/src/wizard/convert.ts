/**
 * Conversion layer between the wizard's typed UI state and the persisted camera
 * configuration DTO (`{ zones: [], event_rules: {} }`).
 *
 * Keeping this separate means the editor can hold transient state (enablement booleans,
 * selection, in-progress shapes) while the saved JSON stays exactly the shape the backend
 * validates (`backend/app/events/zones.py`). Unrelated configuration the wizard does not own
 * — extra top-level keys, `package_classes`, `config_version`, and threshold keys such as
 * `boundary_side_epsilon` — is preserved across a save.
 */

import { KIND_LABELS, requiredRoles, ROLE_LABELS } from './eventCatalog';
import { defaultThresholds, THRESHOLD_DEFINITIONS, thresholdsForEvents } from './thresholdCatalog';
import { roundCoord } from './coordinates';
import { rotationFromConfiguration } from '../lib/videoRotation';
import {
  emptyEvents,
  type EventKey,
  type ThresholdValues,
  type WizardBoundary,
  type WizardPoint,
  type WizardState,
  type WizardZone,
  type ZoneKind,
  type ZoneRole,
} from './wizardTypes';

/** A camera configuration object (only `zones` and `event_rules` are recognised). */
export type CameraConfiguration = Record<string, unknown>;

/** Roles the wizard is responsible for writing. */
export const WIZARD_ROLES: ZoneRole[] = [
  'entrance_zone_id',
  'room_zone_id',
  'door_zone_id',
  'package_zone_id',
  'bed_zone_id',
  'floor_zone_id',
];

/** Threshold keys the wizard exposes. */
export const WIZARD_THRESHOLD_KEYS = THRESHOLD_DEFINITIONS.map((definition) => definition.key);

const ZONE_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const ZONE_KINDS: ZoneKind[] = [
  'entrance',
  'room',
  'door',
  'bed',
  'floor',
  'package_area',
  'other',
];

/** Each zone kind maps to exactly one configuration role (or none, for `other`). */
export function roleForKind(kind: ZoneKind): ZoneRole | null {
  switch (kind) {
    case 'entrance':
      return 'entrance_zone_id';
    case 'room':
      return 'room_zone_id';
    case 'door':
      return 'door_zone_id';
    case 'package_area':
      return 'package_zone_id';
    case 'bed':
      return 'bed_zone_id';
    case 'floor':
      return 'floor_zone_id';
    default:
      return null;
  }
}

function asObject(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function isZoneKind(value: unknown): value is ZoneKind {
  return typeof value === 'string' && (ZONE_KINDS as string[]).includes(value);
}

function isBoundarySide(value: unknown): value is 'left' | 'right' {
  return value === 'left' || value === 'right';
}

function parsePoint(value: unknown): WizardPoint | null {
  const obj = asObject(value);
  const x = obj.x;
  const y = obj.y;
  if (
    typeof x !== 'number' ||
    typeof y !== 'number' ||
    !Number.isFinite(x) ||
    !Number.isFinite(y)
  ) {
    return null;
  }
  return { x, y };
}

function parseBoundary(value: unknown): WizardBoundary | null {
  const obj = asObject(value);
  const p1 = parsePoint(obj.p1);
  const p2 = parsePoint(obj.p2);
  if (p1 === null || p2 === null) return null;
  return { p1, p2, inside_side: isBoundarySide(obj.inside_side) ? obj.inside_side : 'left' };
}

function parseZone(value: unknown): WizardZone | null {
  const obj = asObject(value);
  const id = typeof obj.id === 'string' ? obj.id : null;
  const kind = isZoneKind(obj.kind) ? obj.kind : null;
  if (id === null || kind === null) return null;
  const polygon = Array.isArray(obj.polygon)
    ? obj.polygon.map(parsePoint).filter((point): point is WizardPoint => point !== null)
    : [];
  const name = typeof obj.name === 'string' && obj.name.trim() ? obj.name : KIND_LABELS[kind];
  return { id, name, kind, polygon, boundary: parseBoundary(obj.boundary) };
}

/** Build wizard state from a saved camera configuration. */
export function configToWizard(configuration: CameraConfiguration | null | undefined): WizardState {
  const config = asObject(configuration);
  const zones: WizardZone[] = [];
  if (Array.isArray(config.zones)) {
    for (const raw of config.zones) {
      const zone = parseZone(raw);
      if (zone !== null) zones.push(zone);
    }
  }

  const rules = asObject(config.event_rules);
  const events = emptyEvents();
  const ref = (role: ZoneRole): boolean => typeof rules[role] === 'string' && rules[role] !== '';
  events.person_entering = ref('entrance_zone_id');
  events.person_leaving = ref('entrance_zone_id');
  events.room_occupancy_change = ref('room_zone_id');
  events.crowd_forming = ref('room_zone_id');
  events.package_left_at_entrance = ref('package_zone_id');
  // Motionlessness needs no zone and is always active in the engine.
  events.person_motionless = true;
  // Door-open and fall events have no supported inputs; they stay unavailable.

  const thresholds: ThresholdValues = {};
  const rawThresholds = asObject(rules.thresholds);
  for (const key of WIZARD_THRESHOLD_KEYS) {
    const value = rawThresholds[key];
    if (typeof value === 'number' && Number.isFinite(value)) thresholds[key] = value;
  }

  return { events, zones, thresholds, rotation: rotationFromConfiguration(config) };
}

function zoneToRaw(zone: WizardZone): Record<string, unknown> {
  const raw: Record<string, unknown> = {
    id: zone.id,
    name: zone.name.trim(),
    kind: zone.kind,
    polygon: zone.polygon.map((point) => ({
      x: roundCoord(point.x),
      y: roundCoord(point.y),
    })),
  };
  if (zone.boundary !== null) {
    raw.boundary = {
      p1: { x: roundCoord(zone.boundary.p1.x), y: roundCoord(zone.boundary.p1.y) },
      p2: { x: roundCoord(zone.boundary.p2.x), y: roundCoord(zone.boundary.p2.y) },
      inside_side: zone.boundary.inside_side,
    };
  }
  return raw;
}

/**
 * Build a camera configuration from wizard state, preserving everything the wizard does not
 * own from `original`.
 */
export function wizardToConfig(
  state: WizardState,
  original: CameraConfiguration | null | undefined = {},
): CameraConfiguration {
  const clone: CameraConfiguration = JSON.parse(JSON.stringify(asObject(original)));
  const originalRules = asObject(clone.event_rules);
  const rules: Record<string, unknown> = { ...originalRules };

  // Zones: fully owned by the wizard.
  clone.zones = state.zones.map(zoneToRaw);

  // Rotation: written when the user rotates, and explicitly cleared (0) if the camera had
  // one saved and the user reset it. Omitted entirely when untouched and never set, so an
  // empty configuration keeps its exact `{ zones, event_rules }` shape.
  if (state.rotation !== 0 || Object.prototype.hasOwnProperty.call(clone, 'rotation')) {
    clone.rotation = state.rotation;
  }

  // Roles: drop the wizard-owned role refs, then re-add those the selected events need.
  for (const role of WIZARD_ROLES) delete rules[role];
  const enabledRoles = new Set<ZoneRole>(requiredRoles(state.events));
  for (const zone of state.zones) {
    const role = roleForKind(zone.kind);
    if (role !== null && enabledRoles.has(role)) rules[role] = zone.id;
  }

  // Thresholds: overwrite only the keys relevant to the selected events, leaving any other
  // saved threshold settings untouched.
  const thresholds: Record<string, unknown> = { ...asObject(originalRules.thresholds) };
  const defaults = defaultThresholds();
  for (const definition of thresholdsForEvents(state.events)) {
    const value = state.thresholds[definition.key];
    thresholds[definition.key] =
      typeof value === 'number' && Number.isFinite(value) ? value : defaults[definition.key];
  }
  if (Object.keys(thresholds).length > 0) {
    rules.thresholds = thresholds;
  } else {
    delete rules.thresholds;
  }

  clone.event_rules = rules;
  return clone;
}

export interface WizardValidation {
  valid: boolean;
  errors: string[];
  zoneErrors: Record<string, string[]>;
  missingRoles: ZoneRole[];
}

/** Validate the wizard state against the same rules the backend enforces. */
export function validateWizard(state: WizardState): WizardValidation {
  const errors: string[] = [];
  const zoneErrors: Record<string, string[]> = {};
  const seenIds = new Set<string>();
  const seenRoles = new Set<ZoneRole>();

  for (const zone of state.zones) {
    const problems: string[] = [];
    if (!ZONE_ID_PATTERN.test(zone.id)) {
      problems.push('Zone id must be lower-case letters, digits, dashes or underscores.');
    }
    if (seenIds.has(zone.id)) problems.push('Duplicate zone id.');
    seenIds.add(zone.id);
    if (!zone.name.trim()) problems.push('A zone name is required.');
    if (zone.polygon.length < 3) problems.push('A zone needs at least 3 points.');
    if (zone.polygon.some((point) => point.x < 0 || point.x > 1 || point.y < 0 || point.y > 1)) {
      problems.push('Zone points must lie inside the frame.');
    }
    const role = roleForKind(zone.kind);
    if (role !== null) {
      if (seenRoles.has(role))
        problems.push(`Only one ${KIND_LABELS[zone.kind].toLowerCase()} zone is supported.`);
      seenRoles.add(role);
    }
    if (zone.kind === 'entrance') {
      if (zone.boundary === null) {
        problems.push('An entrance zone needs a boundary line.');
      } else if (
        zone.boundary.p1.x === zone.boundary.p2.x &&
        zone.boundary.p1.y === zone.boundary.p2.y
      ) {
        problems.push('The boundary points must differ.');
      }
    }
    if (problems.length > 0) zoneErrors[zone.id] = problems;
  }

  const missingRoles = requiredRoles(state.events).filter(
    (role) =>
      !state.zones.some((zone) => roleForKind(zone.kind) === role && zone.polygon.length >= 3),
  );
  for (const role of missingRoles) {
    errors.push(`Draw the ${ROLE_LABELS[role]} zone required by the selected events.`);
  }

  for (const definition of thresholdsForEvents(state.events)) {
    const value = state.thresholds[definition.key];
    if (value === undefined) continue;
    if (!Number.isFinite(value) || value < definition.min) {
      errors.push(`${definition.label} must be at least ${definition.min}.`);
    } else if (definition.max !== undefined && value > definition.max) {
      errors.push(`${definition.label} must be at most ${definition.max}.`);
    }
  }

  return {
    valid: errors.length === 0 && Object.keys(zoneErrors).length === 0,
    errors,
    zoneErrors,
    missingRoles,
  };
}

/** Generate a unique, schema-valid zone id for a newly drawn zone. */
export function newZoneId(kind: ZoneKind, existing: WizardZone[]): string {
  const base = kind === 'package_area' ? 'package' : kind;
  const ids = new Set(existing.map((zone) => zone.id));
  let counter = 1;
  let candidate = `${base}-${counter}`;
  while (ids.has(candidate)) {
    counter += 1;
    candidate = `${base}-${counter}`;
  }
  return candidate;
}

/** Convenience predicate for callers building UI. */
export function isEventEnabled(events: Record<EventKey, boolean>, key: EventKey): boolean {
  return events[key] === true;
}
