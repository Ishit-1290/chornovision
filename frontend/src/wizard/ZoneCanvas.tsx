import { useTheme } from '@mui/material/styles';
import type { PointerEvent as ReactPointerEvent } from 'react';

import { fromDisplayPoint, pointerToNormalized, toDisplayPoint } from './coordinates';
import type { WizardPoint, WizardZone } from './wizardTypes';
import type { Rotation } from '../lib/videoRotation';

export type EditorMode = 'select' | 'draw-polygon' | 'draw-boundary';

export interface BoundaryDraft {
  p1: WizardPoint;
  p2: WizardPoint | null;
}

export interface ZoneCanvasProps {
  /** Visible video content size in CSS pixels. */
  width: number;
  height: number;
  /** Clockwise display rotation; geometry is always reported in the original frame. */
  rotation?: Rotation;
  zones: WizardZone[];
  selectedZoneId: string | null;
  draftPolygon: WizardPoint[] | null;
  boundaryDraft: BoundaryDraft | null;
  mode: EditorMode;
  /** Called with a normalised point when the empty canvas is pressed. */
  onSurfacePointerDown: (point: WizardPoint) => void;
  onSurfacePointerMove?: (point: WizardPoint) => void;
  onSelectZone: (zoneId: string) => void;
  /** Begin dragging a polygon vertex. */
  onVertexPointerDown: (zoneId: string, index: number) => void;
  onVertexPointerMove: (zoneId: string, index: number, point: WizardPoint) => void;
  onVertexPointerUp: () => void;
  onBoundaryHandlePointerDown: (zoneId: string, handle: 'p1' | 'p2') => void;
  onBoundaryHandlePointerMove: (zoneId: string, handle: 'p1' | 'p2', point: WizardPoint) => void;
  onBoundaryHandlePointerUp: () => void;
}

const KIND_COLOR_KEYS: Record<string, string> = {
  entrance: 'primary.main',
  room: 'secondary.main',
  package_area: 'warning.main',
  door: 'info.main',
  bed: 'success.main',
  floor: 'text.disabled',
  other: 'text.secondary',
};

const MODE_HINTS: Record<EditorMode, string> = {
  select: 'Select a zone to edit its points.',
  'draw-polygon': 'Tap/click to add points; finish with “Finish zone”.',
  'draw-boundary': 'Tap/click two points for the entrance boundary.',
};

/** Compute the original-frame normalised point for a pointer event, using the SVG that contains it. */
function pointFromEvent(
  event: ReactPointerEvent<Element>,
  width: number,
  height: number,
  rotation: Rotation,
): WizardPoint {
  const element = event.currentTarget;
  const svg = element.closest('svg') ?? element;
  const rect = svg.getBoundingClientRect();
  if (rect.width > 0 && rect.height > 0) {
    return fromDisplayPoint(
      pointerToNormalized(
        { clientX: event.clientX, clientY: event.clientY },
        { left: rect.left, top: rect.top },
        { left: 0, top: 0, width: rect.width, height: rect.height },
      ),
      rotation,
    );
  }
  // No layout (e.g. tests without a stubbed rect): fall back to the declared size.
  if (width > 0 && height > 0) {
    return fromDisplayPoint(
      pointerToNormalized(
        { clientX: event.clientX, clientY: event.clientY },
        { left: 0, top: 0 },
        { left: 0, top: 0, width, height },
      ),
      rotation,
    );
  }
  return { x: 0, y: 0 };
}

/**
 * SVG overlay for drawing and editing zones.
 *
 * The caller sizes this element exactly to the visible (rotated) video content rectangle, so
 * the element's own bounding box *is* the displayed frame. Pointer positions are mapped into
 * display-normalised coordinates and then inverse-rotated back into the original camera frame
 * before they are reported, so stored geometry never depends on the preview orientation.
 * Pointer events cover both mouse and touch.
 */
export function ZoneCanvas({
  width,
  height,
  rotation = 0,
  zones,
  selectedZoneId,
  draftPolygon,
  boundaryDraft,
  mode,
  onSurfacePointerDown,
  onSurfacePointerMove,
  onSelectZone,
  onVertexPointerDown,
  onVertexPointerMove,
  onVertexPointerUp,
  onBoundaryHandlePointerDown,
  onBoundaryHandlePointerMove,
  onBoundaryHandlePointerUp,
}: ZoneCanvasProps) {
  const theme = useTheme();

  /** Map an original-frame point to display pixels (rotation applied). */
  const px = (point: WizardPoint) => {
    const display = toDisplayPoint(point, rotation);
    return { x: display.x * width, y: display.y * height };
  };

  const colorFor = (zone: WizardZone) => {
    const key = KIND_COLOR_KEYS[zone.kind] ?? 'text.primary';
    const parts = key.split('.');
    const group = parts[0] as keyof typeof theme.palette;
    const shade = parts[1] as string;
    const groupValue = theme.palette[group] as unknown as Record<string, string> | undefined;
    return groupValue?.[shade] ?? theme.palette.text.primary;
  };

  /** Unit vector from a boundary midpoint towards its monitored interior (display space). */
  const interiorVector = (zone: WizardZone): WizardPoint | null => {
    if (zone.boundary === null) return null;
    const p1 = toDisplayPoint(zone.boundary.p1, rotation);
    const p2 = toDisplayPoint(zone.boundary.p2, rotation);
    const dx = p2.x - p1.x;
    const dy = p2.y - p1.y;
    const length = Math.hypot(dx, dy);
    if (length === 0) return null;
    // Gradient of the signed side offset: 'left' is the (-dy, dx) side.
    const sign = zone.boundary.inside_side === 'left' ? 1 : -1;
    return { x: (-dy / length) * sign, y: (dx / length) * sign };
  };

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="application"
      aria-label="Zone editor canvas"
      data-testid="zone-canvas"
      style={{
        position: 'absolute',
        inset: 0,
        touchAction: 'none',
        cursor: mode === 'select' ? 'default' : 'crosshair',
      }}
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) {
          onSurfacePointerDown(pointFromEvent(event, width, height, rotation));
        }
      }}
      onPointerMove={(event) => {
        if (event.target === event.currentTarget) {
          onSurfacePointerMove?.(pointFromEvent(event, width, height, rotation));
        }
      }}
    >
      {zones.map((zone) => {
        const selected = zone.id === selectedZoneId;
        const color = colorFor(zone);
        const points = zone.polygon.map(px);
        const path = points.map((point) => `${point.x},${point.y}`).join(' ');
        const interior =
          zone.kind === 'entrance' && zone.boundary !== null ? interiorVector(zone) : null;
        const midpoint =
          zone.boundary !== null
            ? px({
                x: (zone.boundary.p1.x + zone.boundary.p2.x) / 2,
                y: (zone.boundary.p1.y + zone.boundary.p2.y) / 2,
              })
            : null;
        return (
          <g key={zone.id}>
            <polygon
              points={path}
              fill={selected ? `${color}44` : `${color}22`}
              stroke={color}
              strokeWidth={selected ? 3 : 2}
              data-testid={`zone-polygon-${zone.id}`}
              style={{ cursor: 'pointer' }}
              onPointerDown={(event) => {
                event.stopPropagation();
                onSelectZone(zone.id);
              }}
            />
            {zone.boundary !== null && (
              <>
                <line
                  x1={px(zone.boundary.p1).x}
                  y1={px(zone.boundary.p1).y}
                  x2={px(zone.boundary.p2).x}
                  y2={px(zone.boundary.p2).y}
                  stroke={theme.palette.warning.main}
                  strokeWidth={3}
                  strokeDasharray="6 4"
                  data-testid={`boundary-${zone.id}`}
                />
                {interior !== null && midpoint !== null && (
                  <line
                    x1={midpoint.x}
                    y1={midpoint.y}
                    x2={midpoint.x + interior.x * 40}
                    y2={midpoint.y + interior.y * 40}
                    stroke={theme.palette.success.main}
                    strokeWidth={3}
                    markerEnd="url(#interior-arrow)"
                    data-testid={`boundary-interior-${zone.id}`}
                  />
                )}
              </>
            )}
            {selected &&
              points.map((point, index) => (
                <circle
                  key={`${zone.id}-v-${index}`}
                  cx={point.x}
                  cy={point.y}
                  r={7}
                  fill={theme.palette.background.paper}
                  stroke={theme.palette.primary.main}
                  strokeWidth={2}
                  data-testid={`vertex-${zone.id}-${index}`}
                  style={{ cursor: 'grab' }}
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    event.currentTarget.setPointerCapture?.(event.pointerId);
                    onVertexPointerDown(zone.id, index);
                  }}
                  onPointerMove={(event) => {
                    event.stopPropagation();
                    onVertexPointerMove(
                      zone.id,
                      index,
                      pointFromEvent(event, width, height, rotation),
                    );
                  }}
                  onPointerUp={(event) => {
                    event.stopPropagation();
                    onVertexPointerUp();
                  }}
                />
              ))}
            {selected &&
              zone.boundary !== null &&
              (['p1', 'p2'] as const).map((handle) => {
                const point = px(zone.boundary![handle]);
                return (
                  <circle
                    key={`${zone.id}-${handle}`}
                    cx={point.x}
                    cy={point.y}
                    r={8}
                    fill={theme.palette.warning.main}
                    stroke={theme.palette.common.black}
                    strokeWidth={2}
                    data-testid={`boundary-handle-${zone.id}-${handle}`}
                    style={{ cursor: 'grab' }}
                    onPointerDown={(event) => {
                      event.stopPropagation();
                      event.currentTarget.setPointerCapture?.(event.pointerId);
                      onBoundaryHandlePointerDown(zone.id, handle);
                    }}
                    onPointerMove={(event) => {
                      event.stopPropagation();
                      onBoundaryHandlePointerMove(
                        zone.id,
                        handle,
                        pointFromEvent(event, width, height, rotation),
                      );
                    }}
                    onPointerUp={(event) => {
                      event.stopPropagation();
                      onBoundaryHandlePointerUp();
                    }}
                  />
                );
              })}
          </g>
        );
      })}

      {(draftPolygon !== null || boundaryDraft !== null) && (
        <g data-testid="draft-layer">
          {draftPolygon !== null && draftPolygon.length > 0 && (
            <>
              <polyline
                points={draftPolygon
                  .map(px)
                  .map((point) => `${point.x},${point.y}`)
                  .join(' ')}
                fill={`${theme.palette.primary.main}33`}
                stroke={theme.palette.primary.main}
                strokeWidth={2}
              />
              {draftPolygon.map((point, index) => {
                const position = px(point);
                return (
                  <circle
                    key={`draft-${index}`}
                    cx={position.x}
                    cy={position.y}
                    r={5}
                    fill={theme.palette.primary.main}
                  />
                );
              })}
            </>
          )}
          {boundaryDraft !== null && (
            <line
              x1={px(boundaryDraft.p1).x}
              y1={px(boundaryDraft.p1).y}
              x2={px(boundaryDraft.p2 ?? boundaryDraft.p1).x}
              y2={px(boundaryDraft.p2 ?? boundaryDraft.p1).y}
              stroke={theme.palette.warning.main}
              strokeWidth={3}
              strokeDasharray="6 4"
            />
          )}
        </g>
      )}

      <defs>
        <marker
          id="interior-arrow"
          markerWidth="6"
          markerHeight="6"
          refX="5"
          refY="3"
          orient="auto"
        >
          <path d="M0,0 L6,3 L0,6 Z" fill={theme.palette.success.main} />
        </marker>
      </defs>

      <text x={8} y={18} fill={theme.palette.text.secondary} fontSize={12}>
        {zones.length > 0
          ? MODE_HINTS[mode]
          : 'No zones yet — choose an event, then draw its zone.'}
      </text>
    </svg>
  );
}
