/**
 * Pointer → normalised-video coordinate conversion for the zone editor.
 *
 * Zone geometry is persisted normalised to `[0, 1]` against the camera frame
 * (`x=0` left, `x=1` right, `y=0` top, `y=1` bottom). The browser preview is letterboxed
 * (`object-fit: contain`), so a pointer position must first be mapped into the *visible
 * video content rectangle* before it is normalised. These helpers are pure so the maths
 * (including letterboxing and rotation) is unit-testable without a real video element.
 */

import type { Rotation } from '../lib/videoRotation';

export interface Size {
  width: number;
  height: number;
}

export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

/**
 * The rectangle actually covered by the video inside `container` when the content keeps
 * its aspect ratio and is centred (CSS `object-fit: contain`).
 *
 * A zero/degenerate content size falls back to the whole container so callers never divide
 * by zero.
 */
export function getContentRect(container: Size, content: Size): Rect {
  const { width: cw, height: ch } = container;
  if (cw <= 0 || ch <= 0) {
    return { left: 0, top: 0, width: Math.max(0, cw), height: Math.max(0, ch) };
  }
  if (content.width <= 0 || content.height <= 0) {
    return { left: 0, top: 0, width: cw, height: ch };
  }
  const scale = Math.min(cw / content.width, ch / content.height);
  const width = content.width * scale;
  const height = content.height * scale;
  return {
    left: (cw - width) / 2,
    top: (ch - height) / 2,
    width,
    height,
  };
}

/**
 * Convert a pointer position (viewport/client coordinates) into a normalised frame
 * coordinate in `[0, 1]`.
 *
 * `element` is the bounding rectangle of the element the pointer events are attached to
 * (viewport coordinates); `content` is the visible video rectangle *relative to that
 * element* (see {@link getContentRect}). The result is clamped so dragging past an edge
 * sticks to the edge rather than producing out-of-range coordinates.
 */
export function pointerToNormalized(
  pointer: { clientX: number; clientY: number },
  element: { left: number; top: number },
  content: Rect,
): Point {
  const localX = pointer.clientX - element.left - content.left;
  const localY = pointer.clientY - element.top - content.top;
  const x = content.width > 0 ? localX / content.width : 0;
  const y = content.height > 0 ? localY / content.height : 0;
  return { x: clamp01(x), y: clamp01(y) };
}

export function clamp01(value: number): number {
  if (Number.isNaN(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

/**
 * Map a point in the original camera frame to the clockwise-rotated display.
 *
 * A quarter turn swaps the frame's width and height, so normalised coordinates transform as
 * a pure rotation: `x' = 1 - y, y' = x` for 90°. Used to draw stored geometry on a rotated
 * preview, while the stored geometry itself stays in the original camera frame (D-72/D-73).
 */
export function toDisplayPoint(point: Point, rotation: Rotation): Point {
  switch (rotation) {
    case 90:
      return { x: 1 - point.y, y: point.x };
    case 180:
      return { x: 1 - point.x, y: 1 - point.y };
    case 270:
      return { x: point.y, y: 1 - point.x };
    default:
      return { x: point.x, y: point.y };
  }
}

/** Inverse of {@link toDisplayPoint}: map a display point back to the camera frame. */
export function fromDisplayPoint(point: Point, rotation: Rotation): Point {
  switch (rotation) {
    case 90:
      return { x: point.y, y: 1 - point.x };
    case 180:
      return { x: 1 - point.x, y: 1 - point.y };
    case 270:
      return { x: 1 - point.y, y: point.x };
    default:
      return { x: point.x, y: point.y };
  }
}

/** Round to a fixed number of decimals so generated JSON stays readable/stable. */
export function roundCoord(value: number, decimals = 4): number {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}
