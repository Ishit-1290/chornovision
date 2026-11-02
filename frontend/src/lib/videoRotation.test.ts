import { describe, expect, it } from 'vitest';

import {
  DEFAULT_SOURCE,
  displayAspect,
  layoutVideo,
  normalizeRotation,
  rotationFromConfiguration,
  rotateCCW,
  rotateCW,
} from './videoRotation';
import type { Rotation } from './videoRotation';

const SOURCE = { width: 960, height: 540 }; // landscape frame from a portrait phone

describe('normalizeRotation', () => {
  it('snaps any angle to the nearest quarter turn', () => {
    expect(normalizeRotation(0)).toBe(0);
    expect(normalizeRotation(44)).toBe(0);
    expect(normalizeRotation(46)).toBe(90);
    expect(normalizeRotation(95)).toBe(90);
    expect(normalizeRotation(269)).toBe(270);
  });

  it('wraps negatives and full turns into [0, 360)', () => {
    expect(normalizeRotation(-90)).toBe(270);
    expect(normalizeRotation(-180)).toBe(180);
    expect(normalizeRotation(360)).toBe(0);
    expect(normalizeRotation(450)).toBe(90);
  });

  it('treats a non-finite angle as no rotation', () => {
    expect(normalizeRotation(Number.NaN)).toBe(0);
    expect(normalizeRotation(Number.POSITIVE_INFINITY)).toBe(0);
  });
});

describe('rotateCW / rotateCCW', () => {
  it('cycles through all four quarter turns', () => {
    const seen: Rotation[] = [];
    let rotation: Rotation = 0;
    for (let i = 0; i < 4; i += 1) {
      rotation = rotateCW(rotation);
      seen.push(rotation);
    }
    expect(seen).toEqual([90, 180, 270, 0]);
  });

  it('is the inverse of itself', () => {
    expect(rotateCCW(rotateCW(90))).toBe(90);
    expect(rotateCCW(0)).toBe(270);
    expect(rotateCW(270)).toBe(0);
  });
});

describe('displayAspect', () => {
  it('keeps the source aspect for upright rotations', () => {
    expect(displayAspect(0, SOURCE)).toBeCloseTo(960 / 540);
    expect(displayAspect(180, SOURCE)).toBeCloseTo(960 / 540);
  });

  it('swaps the aspect for a quarter turn, making a portrait feed portrait', () => {
    expect(displayAspect(90, SOURCE)).toBeCloseTo(540 / 960);
    expect(displayAspect(270, SOURCE)).toBeCloseTo(540 / 960);
  });

  it('falls back to 16:9 for a degenerate source', () => {
    expect(displayAspect(0, { width: 0, height: 0 })).toBeCloseTo(16 / 9);
    expect(displayAspect(90, DEFAULT_SOURCE)).toBeCloseTo(9 / 16);
  });
});

describe('layoutVideo', () => {
  it('fills the container for an upright frame', () => {
    expect(layoutVideo(0, { width: 800, height: 450 }, SOURCE)).toMatchObject({
      position: 'absolute',
      width: '100%',
      height: '100%',
      transform: 'none',
    });
  });

  it('rotates the full container in place for 180 degrees', () => {
    expect(layoutVideo(180, { width: 800, height: 450 }, SOURCE).transform).toBe('rotate(180deg)');
  });

  it('transposes the layout box for 90 degrees so the rotated frame fits', () => {
    const style = layoutVideo(90, { width: 800, height: 450 }, SOURCE);
    expect(style.transform).toBe('translate(-50%, -50%) rotate(90deg)');
    // boxWidth is clamped to the container's height, and boxHeight keeps the source aspect.
    expect(style.width).toBe('450px');
    expect(style.height).toBe('253.125px');
    // The rotated bounding box (height x width) never exceeds the container.
    expect(253.125).toBeLessThanOrEqual(800);
    expect(450).toBeLessThanOrEqual(450);
  });

  it('fills a matching portrait container exactly for 270 degrees', () => {
    // Container has the source's transposed aspect (540 x 960 scaled).
    const container = { width: 400, height: 400 * (960 / 540) };
    const style = layoutVideo(270, container, SOURCE);
    expect(Number.parseFloat(String(style.width))).toBeCloseTo(container.height, 6);
    expect(Number.parseFloat(String(style.height))).toBeCloseTo(container.width, 6);
    expect(style.transform).toBe('translate(-50%, -50%) rotate(270deg)');
  });

  it('falls back to filling the container when the size is not yet known', () => {
    const style = layoutVideo(90, { width: 0, height: 0 }, SOURCE);
    expect(style.width).toBe('100%');
    expect(style.height).toBe('100%');
    expect(style.transform).toBe('rotate(90deg)');
  });
});

describe('rotationFromConfiguration', () => {
  it('reads a supported rotation from the camera configuration', () => {
    expect(rotationFromConfiguration({ rotation: 90 })).toBe(90);
    expect(rotationFromConfiguration({ rotation: 270 })).toBe(270);
    expect(rotationFromConfiguration({ rotation: '180' })).toBe(180);
  });

  it('defaults to 0 when unset or malformed', () => {
    expect(rotationFromConfiguration({})).toBe(0);
    expect(rotationFromConfiguration(null)).toBe(0);
    expect(rotationFromConfiguration(undefined)).toBe(0);
    expect(rotationFromConfiguration({ rotation: 'sideways' })).toBe(0);
    expect(rotationFromConfiguration({ rotation: 45 })).toBe(90);
  });
});
