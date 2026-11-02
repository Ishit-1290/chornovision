/**
 * Typed UI state for the zone & event setup wizard.
 *
 * This is deliberately **separate** from the persisted configuration DTO
 * (`{ zones: [], event_rules: {} }`). The conversion layer in `convert.ts` translates
 * between the two, so the editor can hold transient concepts (selection, in-progress
 * shapes, enablement booleans) that have no place in the saved JSON.
 */

import type { Rotation } from '../lib/videoRotation';

export type ZoneKind = 'entrance' | 'room' | 'door' | 'bed' | 'floor' | 'package_area' | 'other';

export type BoundarySide = 'left' | 'right';

export type EventKey =
  | 'person_entering'
  | 'person_leaving'
  | 'room_occupancy_change'
  | 'crowd_forming'
  | 'person_motionless'
  | 'package_left_at_entrance'
  | 'door_open_too_long'
  | 'fall_from_bed';

/** The configuration role a zone can be referenced by. */
export type ZoneRole =
  | 'entrance_zone_id'
  | 'room_zone_id'
  | 'door_zone_id'
  | 'package_zone_id'
  | 'bed_zone_id'
  | 'floor_zone_id';

export interface WizardPoint {
  x: number;
  y: number;
}

export interface WizardBoundary {
  p1: WizardPoint;
  p2: WizardPoint;
  inside_side: BoundarySide;
}

export interface WizardZone {
  id: string;
  name: string;
  kind: ZoneKind;
  polygon: WizardPoint[];
  boundary: WizardBoundary | null;
}

/** Threshold values the wizard exposes, keyed by their backend configuration name. */
export type ThresholdKey =
  | 'boundary_confirm_frames'
  | 'boundary_cooldown_seconds'
  | 'occupancy_persistence_seconds'
  | 'occupancy_retention_seconds'
  | 'crowd_occupancy_threshold'
  | 'crowd_persistence_seconds'
  | 'crowd_release_seconds'
  | 'motionless_duration_seconds'
  | 'motionless_movement_threshold'
  | 'motionless_min_observations'
  | 'package_stationary_seconds'
  | 'package_person_proximity';

export type ThresholdValues = Partial<Record<ThresholdKey, number>>;

export interface WizardState {
  /** Which supported events the user has selected. */
  events: Record<EventKey, boolean>;
  zones: WizardZone[];
  /** Only keys the wizard owns; unrelated saved thresholds are merged back on save. */
  thresholds: ThresholdValues;
  /**
   * Display/detection rotation in degrees clockwise. Persisted as `configuration.rotation`;
   * the preview is shown rotated while zones are stored in the original camera frame.
   */
  rotation: Rotation;
}

export function emptyEvents(): Record<EventKey, boolean> {
  return {
    person_entering: false,
    person_leaving: false,
    room_occupancy_change: false,
    crowd_forming: false,
    person_motionless: false,
    package_left_at_entrance: false,
    door_open_too_long: false,
    fall_from_bed: false,
  };
}

export function emptyWizardState(): WizardState {
  return { events: emptyEvents(), zones: [], thresholds: {}, rotation: 0 };
}
