import { describe, expect, it } from 'vitest';

import {
  clamp01,
  fromDisplayPoint,
  getContentRect,
  pointerToNormalized,
  roundCoord,
  toDisplayPoint,
} from './coordinates';

describe('getContentRect', () => {
  it('fills the container when the aspect ratios match', () => {
    expect(getContentRect({ width: 800, height: 450 }, { width: 16, height: 9 })).toEqual({
      left: 0,
      top: 0,
      width: 800,
      height: 450,
    });
  });

  it('letterboxes a wide video inside a taller container (pillarbox top/bottom)', () => {
    // 960x540 content in a 800x600 container => scaled to 800x450, centred vertically.
    const rect = getContentRect({ width: 800, height: 600 }, { width: 960, height: 540 });
    expect(rect.width).toBe(800);
    expect(rect.height).toBe(450);
    expect(rect.left).toBe(0);
    expect(rect.top).toBe(75);
  });

  it('pillarboxes a tall video inside a wider container (bars left/right)', () => {
    // 9x16 portrait in a 400x400 container => 225x400, centred horizontally.
    const rect = getContentRect({ width: 400, height: 400 }, { width: 9, height: 16 });
    expect(rect.height).toBe(400);
    expect(rect.width).toBeCloseTo(225, 5);
    expect(rect.left).toBeCloseTo(87.5, 5);
    expect(rect.top).toBe(0);
  });

  it('falls back to the whole container for degenerate video metadata', () => {
    expect(getContentRect({ width: 300, height: 200 }, { width: 0, height: 0 })).toEqual({
      left: 0,
      top: 0,
      width: 300,
      height: 200,
    });
  });
});

describe('pointerToNormalized', () => {
  const content = { left: 0, top: 75, width: 800, height: 450 };

  it('maps corners of the visible content to 0 and 1', () => {
    expect(pointerToNormalized({ clientX: 0, clientY: 75 }, { left: 0, top: 0 }, content)).toEqual({
      x: 0,
      y: 0,
    });
    expect(
      pointerToNormalized({ clientX: 800, clientY: 525 }, { left: 0, top: 0 }, content),
    ).toEqual({ x: 1, y: 1 });
  });

  it('maps the visual centre to (0.5, 0.5)', () => {
    const point = pointerToNormalized(
      { clientX: 400, clientY: 75 + 225 },
      { left: 0, top: 0 },
      content,
    );
    expect(point.x).toBeCloseTo(0.5, 6);
    expect(point.y).toBeCloseTo(0.5, 6);
  });

  it('accounts for the element origin and letterbox offset', () => {
    // Element sits at (100, 20); content starts 75px into it.
    const element = { left: 100, top: 20 };
    const local = { left: 0, top: 75, width: 800, height: 450 };
    const point = pointerToNormalized(
      { clientX: 100 + 800, clientY: 20 + 75 + 450 },
      element,
      local,
    );
    expect(point).toEqual({ x: 1, y: 1 });
  });

  it('clamps pointer positions outside the visible content', () => {
    expect(
      pointerToNormalized({ clientX: -50, clientY: -50 }, { left: 0, top: 0 }, content),
    ).toEqual({ x: 0, y: 0 });
    expect(
      pointerToNormalized({ clientX: 9999, clientY: 9999 }, { left: 0, top: 0 }, content),
    ).toEqual({ x: 1, y: 1 });
  });
});

describe('clamp01 / roundCoord', () => {
  it('clamps and guards NaN', () => {
    expect(clamp01(-1)).toBe(0);
    expect(clamp01(2)).toBe(1);
    expect(clamp01(Number.NaN)).toBe(0);
  });

  it('rounds for stable JSON output', () => {
    expect(roundCoord(0.123456)).toBe(0.1235);
    expect(roundCoord(1)).toBe(1);
  });
});

describe('display rotation', () => {
  it('is the identity for 0 degrees', () => {
    expect(toDisplayPoint({ x: 0.2, y: 0.8 }, 0)).toEqual({ x: 0.2, y: 0.8 });
    expect(fromDisplayPoint({ x: 0.2, y: 0.8 }, 0)).toEqual({ x: 0.2, y: 0.8 });
  });

  it('rotates 90 degrees clockwise: (x, y) -> (1 - y, x)', () => {
    const point = toDisplayPoint({ x: 0.2, y: 0.8 }, 90);
    expect(point.x).toBeCloseTo(0.2, 6);
    expect(point.y).toBeCloseTo(0.2, 6);
    expect(toDisplayPoint({ x: 0, y: 0 }, 90)).toEqual({ x: 1, y: 0 });
  });

  it('is its own inverse for 180 degrees', () => {
    expect(toDisplayPoint({ x: 0.25, y: 0.75 }, 180)).toEqual({ x: 0.75, y: 0.25 });
    expect(fromDisplayPoint({ x: 0.75, y: 0.25 }, 180)).toEqual({ x: 0.25, y: 0.75 });
  });

  it('rotates 270 degrees clockwise and round-trips every quarter turn', () => {
    const point = toDisplayPoint({ x: 0.2, y: 0.8 }, 270);
    expect(point.x).toBeCloseTo(0.8, 6);
    expect(point.y).toBeCloseTo(0.8, 6);
    for (const rotation of [0, 90, 180, 270] as const) {
      const original = { x: 0.3, y: 0.6 };
      const roundTripped = fromDisplayPoint(toDisplayPoint(original, rotation), rotation);
      expect(roundTripped.x).toBeCloseTo(original.x, 6);
      expect(roundTripped.y).toBeCloseTo(original.y, 6);
    }
  });
});
