import type { CSSProperties } from 'react';

import type { Size } from './useElementSize';

/**
 * Quarter-turn rotation for camera feeds whose frames arrive sideways (e.g. a phone held
 * in portrait publishing a landscape RTSP stream).
 *
 * The rotation is a **per-camera setting** stored in the camera's `configuration` JSON
 * (`rotation`). The live player uses it to display the picture upright, and the vision
 * worker uses the same value to rotate frames *for the detector only* — the stored zone
 * geometry stays in the original camera frame, so no zones ever need redrawing (D-72).
 */
export type Rotation = 0 | 90 | 180 | 270;

/** Assumed source aspect (16:9) until the video element reports its real dimensions. */
export const DEFAULT_SOURCE: Size = { width: 16, height: 9 };

/** Read a camera's persisted detection rotation from its `configuration` JSON. */
export function rotationFromConfiguration(
  configuration: Record<string, unknown> | null | undefined,
): Rotation {
  const value = configuration?.['rotation'];
  if (typeof value === 'number') return normalizeRotation(value);
  if (typeof value === 'string') return normalizeRotation(Number(value));
  return 0;
}

/** Snap any number of degrees to the nearest supported quarter turn. */
export function normalizeRotation(degrees: number): Rotation {
  if (!Number.isFinite(degrees)) return 0;
  const snapped = ((Math.round(degrees / 90) % 4) + 4) % 4;
  return (snapped * 90) as Rotation;
}

/** Rotate one quarter turn clockwise. */
export function rotateCW(rotation: Rotation): Rotation {
  return normalizeRotation(rotation + 90);
}

/** Rotate one quarter turn counter-clockwise. */
export function rotateCCW(rotation: Rotation): Rotation {
  return normalizeRotation(rotation - 90);
}

/**
 * Aspect ratio (`width / height`) of the *displayed* frame. A quarter turn swaps the source
 * aspect, so a sideways portrait stream shows as portrait.
 */
export function displayAspect(rotation: Rotation, source: Size = DEFAULT_SOURCE): number {
  const { width, height } = source;
  if (width <= 0 || height <= 0) return DEFAULT_SOURCE.width / DEFAULT_SOURCE.height;
  return rotation === 90 || rotation === 270 ? height / width : width / height;
}

/**
 * Inline style for the `<video>` inside a measured container so the rotated frame is shown
 * fully (letterboxed, never cropped) and never distorted.
 *
 * For `0`/`180` the element fills the container and is rotated in place. For `90`/`270` the
 * element's *layout* box must be transposed — its rotated bounding box occupies
 * `height × width` — so it is sized from the container and centred before rotating. When the
 * container size is not yet known the element simply fills the container.
 */
export function layoutVideo(
  rotation: Rotation,
  container: Size,
  source: Size = DEFAULT_SOURCE,
): CSSProperties {
  const { width: cw, height: ch } = container;
  const { width: vw, height: vh } = source;

  if ((rotation === 90 || rotation === 270) && cw > 0 && ch > 0 && vw > 0 && vh > 0) {
    // Fit the transposed box: visual width = boxHeight, visual height = boxWidth.
    const boxWidth = Math.min(ch, (cw * vw) / vh);
    const boxHeight = (boxWidth * vh) / vw;
    return {
      position: 'absolute',
      objectFit: 'contain',
      left: '50%',
      top: '50%',
      width: `${boxWidth}px`,
      height: `${boxHeight}px`,
      maxWidth: 'none',
      transform: `translate(-50%, -50%) rotate(${rotation}deg)`,
    };
  }

  return {
    position: 'absolute',
    objectFit: 'contain',
    left: '0',
    top: '0',
    width: '100%',
    height: '100%',
    maxWidth: 'none',
    transform: rotation === 0 ? 'none' : `rotate(${rotation}deg)`,
  };
}
