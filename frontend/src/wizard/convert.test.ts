import { describe, expect, it } from 'vitest';

import { configToWizard, newZoneId, roleForKind, validateWizard, wizardToConfig } from './convert';
import type { WizardState, WizardZone } from './wizardTypes';
import { emptyEvents, emptyWizardState } from './wizardTypes';

function roomZone(id = 'room-1'): WizardZone {
  return {
    id,
    name: 'Room',
    kind: 'room',
    polygon: [
      { x: 0.1, y: 0.1 },
      { x: 0.9, y: 0.1 },
      { x: 0.9, y: 0.9 },
      { x: 0.1, y: 0.9 },
    ],
    boundary: null,
  };
}

function entranceZone(id = 'entrance-1'): WizardZone {
  return {
    id,
    name: 'Entrance',
    kind: 'entrance',
    polygon: [
      { x: 0.2, y: 0.2 },
      { x: 0.8, y: 0.2 },
      { x: 0.8, y: 0.8 },
    ],
    boundary: { p1: { x: 0.2, y: 0.5 }, p2: { x: 0.8, y: 0.5 }, inside_side: 'left' },
  };
}

describe('roleForKind', () => {
  it('maps each supported kind to its configuration role', () => {
    expect(roleForKind('entrance')).toBe('entrance_zone_id');
    expect(roleForKind('room')).toBe('room_zone_id');
    expect(roleForKind('package_area')).toBe('package_zone_id');
    expect(roleForKind('other')).toBeNull();
  });
});

describe('configToWizard', () => {
  it('returns an empty state for an empty configuration', () => {
    const state = configToWizard({});
    expect(state.zones).toEqual([]);
    expect(state.events.person_entering).toBe(false);
    expect(state.events.person_motionless).toBe(true);
  });

  it('maps zones, enabled events and saved thresholds', () => {
    const state = configToWizard({
      zones: [
        {
          id: 'entrance-1',
          name: 'Front door',
          kind: 'entrance',
          polygon: [
            { x: 0.1, y: 0.1 },
            { x: 0.9, y: 0.1 },
            { x: 0.9, y: 0.9 },
          ],
          boundary: { p1: { x: 0.1, y: 0.5 }, p2: { x: 0.9, y: 0.5 }, inside_side: 'right' },
        },
        {
          id: 'room-1',
          name: 'Living room',
          kind: 'room',
          polygon: [
            { x: 0.2, y: 0.2 },
            { x: 0.8, y: 0.2 },
            { x: 0.8, y: 0.8 },
          ],
        },
      ],
      event_rules: {
        entrance_zone_id: 'entrance-1',
        room_zone_id: 'room-1',
        thresholds: { boundary_confirm_frames: 4, crowd_occupancy_threshold: 6 },
      },
    });

    expect(state.zones).toHaveLength(2);
    expect(state.events.person_entering).toBe(true);
    expect(state.events.person_leaving).toBe(true);
    expect(state.events.room_occupancy_change).toBe(true);
    expect(state.events.crowd_forming).toBe(true);
    expect(state.events.package_left_at_entrance).toBe(false);
    expect(state.thresholds.boundary_confirm_frames).toBe(4);
    expect(state.thresholds.crowd_occupancy_threshold).toBe(6);
    expect(state.zones[0].boundary?.inside_side).toBe('right');
  });

  it('ignores malformed zones rather than throwing', () => {
    const state = configToWizard({ zones: [null, { id: 'x' }, 42, { id: 'ok', kind: 'room' }] });
    expect(state.zones.map((zone) => zone.id)).toEqual(['ok']);
  });
});

describe('wizardToConfig — correct JSON for supported events', () => {
  it('writes entrance role + boundary for entering/leaving', () => {
    const state: WizardState = {
      events: { ...emptyEvents(), person_entering: true, person_leaving: true },
      zones: [entranceZone()],
      thresholds: {},
      rotation: 0,
    };
    const config = wizardToConfig(state);
    expect(config.zones).toEqual([
      {
        id: 'entrance-1',
        name: 'Entrance',
        kind: 'entrance',
        polygon: [
          { x: 0.2, y: 0.2 },
          { x: 0.8, y: 0.2 },
          { x: 0.8, y: 0.8 },
        ],
        boundary: { p1: { x: 0.2, y: 0.5 }, p2: { x: 0.8, y: 0.5 }, inside_side: 'left' },
      },
    ]);
    expect((config.event_rules as Record<string, unknown>).entrance_zone_id).toBe('entrance-1');
    expect((config.event_rules as Record<string, unknown>).room_zone_id).toBeUndefined();
  });

  it('writes the room role for occupancy and crowd', () => {
    const state: WizardState = {
      events: { ...emptyEvents(), room_occupancy_change: true, crowd_forming: true },
      zones: [roomZone()],
      thresholds: {},
      rotation: 0,
    };
    const config = wizardToConfig(state);
    expect((config.event_rules as Record<string, unknown>).room_zone_id).toBe('room-1');
  });

  it('writes the package role for package detection', () => {
    const state: WizardState = {
      events: { ...emptyEvents(), package_left_at_entrance: true },
      zones: [{ ...roomZone('package-1'), kind: 'package_area', name: 'Package area' }],
      thresholds: {},
      rotation: 0,
    };
    const config = wizardToConfig(state);
    expect((config.event_rules as Record<string, unknown>).package_zone_id).toBe('package-1');
  });

  it('never writes door/fall events (unsupported inputs)', () => {
    const state: WizardState = {
      events: {
        ...emptyEvents(),
        door_open_too_long: true,
        fall_from_bed: true,
        person_motionless: true,
      },
      zones: [],
      thresholds: {},
      rotation: 0,
    };
    const rules = wizardToConfig(state).event_rules as Record<string, unknown>;
    expect(rules.door_zone_id).toBeUndefined();
    expect(rules.bed_zone_id).toBeUndefined();
  });

  it('produces motionless thresholds without any zone', () => {
    const state: WizardState = {
      events: { ...emptyEvents(), person_motionless: true },
      zones: [],
      thresholds: { motionless_duration_seconds: 90 },
      rotation: 0,
    };
    const config = wizardToConfig(state);
    expect(config.zones).toEqual([]);
    const rules = config.event_rules as Record<string, unknown>;
    expect(rules.entrance_zone_id).toBeUndefined();
    expect((rules.thresholds as Record<string, number>).motionless_duration_seconds).toBe(90);
    // Defaults for other relevant motionless keys are filled in.
    expect((rules.thresholds as Record<string, number>).motionless_min_observations).toBe(5);
  });

  it('writes only the exact { zones, event_rules } shape when starting empty', () => {
    const config = wizardToConfig(emptyWizardState());
    expect(Object.keys(config).sort()).toEqual(['event_rules', 'zones']);
  });

  it('round-trips through configToWizard', () => {
    const original: WizardState = {
      events: {
        ...emptyEvents(),
        person_entering: true,
        person_leaving: true,
        room_occupancy_change: true,
        crowd_forming: true,
        person_motionless: true,
        package_left_at_entrance: true,
      },
      zones: [entranceZone(), roomZone(), { ...roomZone('package-1'), kind: 'package_area' }],
      thresholds: { boundary_confirm_frames: 3, crowd_occupancy_threshold: 5 },
      rotation: 90,
    };
    const config = wizardToConfig(original);
    const reloaded = configToWizard(config);
    expect(reloaded.events).toEqual(original.events);
    expect(reloaded.zones).toEqual(original.zones);
    expect(reloaded.thresholds.boundary_confirm_frames).toBe(3);
    expect(reloaded.thresholds.crowd_occupancy_threshold).toBe(5);
    expect(reloaded.rotation).toBe(90);
  });

  it('writes the rotation and reads it back', () => {
    const state: WizardState = {
      events: { ...emptyEvents(), room_occupancy_change: true },
      zones: [roomZone()],
      thresholds: {},
      rotation: 270,
    };
    expect(wizardToConfig(state).rotation).toBe(270);
    expect(configToWizard({ rotation: 270 }).rotation).toBe(270);
  });

  it('omits an untouched zero rotation but clears a saved one on reset', () => {
    const untouched = wizardToConfig(emptyWizardState());
    expect(Object.keys(untouched).sort()).toEqual(['event_rules', 'zones']);
    expect('rotation' in untouched).toBe(false);

    const reset: WizardState = {
      events: { ...emptyEvents(), room_occupancy_change: true },
      zones: [roomZone()],
      thresholds: {},
      rotation: 0,
    };
    expect(wizardToConfig(reset, { rotation: 90 }).rotation).toBe(0);
  });
});

describe('wizardToConfig — preserves unrelated configuration', () => {
  it('keeps top-level keys and unowned event_rules', () => {
    const original = {
      vendor_metadata: { note: 'keep me' },
      zones: [{ id: 'old', name: 'Old', kind: 'other', polygon: [] }],
      event_rules: {
        config_version: '7',
        package_classes: ['parcel'],
        thresholds: { boundary_side_epsilon: 0.02, crowd_occupancy_threshold: 9 },
      },
    };
    const state: WizardState = {
      events: { ...emptyEvents(), room_occupancy_change: true, person_motionless: true },
      zones: [roomZone()],
      thresholds: {},
      rotation: 0,
    };
    const config = wizardToConfig(state, original);
    expect(config.vendor_metadata).toEqual({ note: 'keep me' });
    const rules = config.event_rules as Record<string, unknown>;
    expect(rules.config_version).toBe('7');
    expect(rules.package_classes).toEqual(['parcel']);
    expect((rules.thresholds as Record<string, number>).boundary_side_epsilon).toBe(0.02);
    // Unrelated crowd threshold (crowd_forming not selected) survives untouched.
    expect((rules.thresholds as Record<string, number>).crowd_occupancy_threshold).toBe(9);
    // The wizard writes defaults for the thresholds it owns and that are relevant.
    expect((rules.thresholds as Record<string, number>).occupancy_persistence_seconds).toBe(2);
  });
});

describe('validateWizard', () => {
  it('flags missing required zones for selected events', () => {
    const result = validateWizard({
      events: { ...emptyEvents(), person_entering: true, person_leaving: true },
      zones: [],
      thresholds: {},
      rotation: 0,
    });
    expect(result.valid).toBe(false);
    expect(result.missingRoles).toContain('entrance_zone_id');
  });

  it('accepts motionless with no zone and no entrance event', () => {
    const result = validateWizard({
      events: { ...emptyEvents(), person_motionless: true },
      zones: [],
      thresholds: {},
      rotation: 0,
    });
    expect(result.valid).toBe(true);
  });

  it('rejects a polygon with fewer than three points', () => {
    const result = validateWizard({
      events: { ...emptyEvents(), room_occupancy_change: true },
      zones: [
        {
          ...roomZone(),
          polygon: [
            { x: 0.1, y: 0.1 },
            { x: 0.5, y: 0.5 },
          ],
        },
      ],
      thresholds: {},
      rotation: 0,
    });
    expect(result.valid).toBe(false);
    expect(result.zoneErrors['room-1']).toContain('A zone needs at least 3 points.');
  });

  it('requires a boundary for an entrance zone', () => {
    const result = validateWizard({
      events: { ...emptyEvents(), person_entering: true },
      zones: [{ ...entranceZone(), boundary: null }],
      thresholds: {},
      rotation: 0,
    });
    expect(result.valid).toBe(false);
    expect(result.zoneErrors['entrance-1']).toContain('An entrance zone needs a boundary line.');
  });

  it('rejects duplicate zone ids and out-of-range points', () => {
    const result = validateWizard({
      events: { ...emptyEvents(), room_occupancy_change: true },
      zones: [
        roomZone('same'),
        {
          ...roomZone('same'),
          polygon: [
            { x: 1.5, y: 0.5 },
            { x: 0.5, y: 0.5 },
            { x: 0.2, y: 0.9 },
          ],
        },
      ],
      thresholds: {},
      rotation: 0,
    });
    expect(result.zoneErrors.same).toContain('Duplicate zone id.');
    expect(result.zoneErrors.same).toContain('Zone points must lie inside the frame.');
  });

  it('rejects out-of-range thresholds', () => {
    const result = validateWizard({
      events: { ...emptyEvents(), person_motionless: true },
      zones: [],
      thresholds: { motionless_min_observations: 0 },
      rotation: 0,
    });
    expect(result.valid).toBe(false);
    expect(result.errors.join(' ')).toMatch(/Minimum observations must be at least 1/);
  });
});

describe('newZoneId', () => {
  it('generates unique, schema-valid ids', () => {
    expect(newZoneId('room', [])).toBe('room-1');
    expect(newZoneId('room', [roomZone('room-1'), roomZone('room-2')])).toBe('room-3');
    expect(newZoneId('package_area', [])).toBe('package-1');
  });
});
