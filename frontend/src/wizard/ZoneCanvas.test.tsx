import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ThemeProvider } from '@mui/material/styles';

import { ZoneCanvas } from './ZoneCanvas';
import type { WizardZone } from './wizardTypes';
import { theme } from '../theme';

const WIDTH = 800;
const HEIGHT = 450;

const zone: WizardZone = {
  id: 'entrance-1',
  name: 'Entrance',
  kind: 'entrance',
  polygon: [
    { x: 0.1, y: 0.1 },
    { x: 0.9, y: 0.1 },
    { x: 0.9, y: 0.9 },
    { x: 0.1, y: 0.9 },
  ],
  boundary: { p1: { x: 0.1, y: 0.5 }, p2: { x: 0.9, y: 0.5 }, inside_side: 'left' },
};

function renderCanvas(overrides: Partial<Parameters<typeof ZoneCanvas>[0]> = {}) {
  const handlers = {
    onSurfacePointerDown: vi.fn(),
    onSurfacePointerMove: vi.fn(),
    onSelectZone: vi.fn(),
    onVertexPointerDown: vi.fn(),
    onVertexPointerMove: vi.fn(),
    onVertexPointerUp: vi.fn(),
    onBoundaryHandlePointerDown: vi.fn(),
    onBoundaryHandlePointerMove: vi.fn(),
    onBoundaryHandlePointerUp: vi.fn(),
  };
  const props = {
    width: WIDTH,
    height: HEIGHT,
    zones: [zone],
    selectedZoneId: 'entrance-1',
    draftPolygon: null,
    boundaryDraft: null,
    mode: 'select' as const,
    ...handlers,
    ...overrides,
  };
  render(
    <ThemeProvider theme={theme}>
      <ZoneCanvas {...props} />
    </ThemeProvider>,
  );
  return handlers;
}

describe('ZoneCanvas', () => {
  beforeEach(() => {
    // jsdom has no layout; give the SVG a deterministic bounding box.
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      right: WIDTH,
      bottom: HEIGHT,
      width: WIDTH,
      height: HEIGHT,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('converts a surface pointer press into a normalised point', () => {
    const handlers = renderCanvas({ mode: 'draw-polygon', draftPolygon: [] });
    fireEvent.pointerDown(screen.getByTestId('zone-canvas'), { clientX: 400, clientY: 225 });
    expect(handlers.onSurfacePointerDown).toHaveBeenCalledWith({ x: 0.5, y: 0.5 });
  });

  it('accepts touch pointer input as well as mouse', () => {
    const handlers = renderCanvas({ mode: 'draw-polygon', draftPolygon: [] });
    fireEvent.pointerDown(screen.getByTestId('zone-canvas'), {
      clientX: 80,
      clientY: 45,
      pointerType: 'touch',
      pointerId: 7,
    });
    expect(handlers.onSurfacePointerDown).toHaveBeenCalledWith({ x: 0.1, y: 0.1 });
  });

  it('selects a polygon when it is pressed', () => {
    const handlers = renderCanvas();
    fireEvent.pointerDown(screen.getByTestId('zone-polygon-entrance-1'));
    expect(handlers.onSelectZone).toHaveBeenCalledWith('entrance-1');
  });

  it('reports vertex drags for the selected zone', () => {
    const handlers = renderCanvas();
    fireEvent.pointerMove(screen.getByTestId('vertex-entrance-1-0'), {
      clientX: 240,
      clientY: 90,
    });
    expect(handlers.onVertexPointerMove).toHaveBeenCalledWith('entrance-1', 0, { x: 0.3, y: 0.2 });
  });

  it('reports boundary handle drags', () => {
    const handlers = renderCanvas();
    fireEvent.pointerMove(screen.getByTestId('boundary-handle-entrance-1-p2'), {
      clientX: 400,
      clientY: 450,
    });
    expect(handlers.onBoundaryHandlePointerMove).toHaveBeenCalledWith('entrance-1', 'p2', {
      x: 0.5,
      y: 1,
    });
  });

  it('draws an interior-direction indicator for an entrance boundary', () => {
    renderCanvas();
    expect(screen.getByTestId('boundary-interior-entrance-1')).toBeInTheDocument();
  });

  it('does not render an interior indicator without a boundary', () => {
    renderCanvas({ zones: [{ ...zone, boundary: null }] });
    expect(screen.queryByTestId('boundary-interior-entrance-1')).not.toBeInTheDocument();
  });

  it('inverse-rotates pointer input when the preview is rotated', () => {
    const handlers = renderCanvas({ mode: 'draw-polygon', draftPolygon: [], rotation: 90 });
    // Display (0.1, 0.1) is original-frame (0.1, 0.9) after undoing a 90° clockwise turn.
    fireEvent.pointerDown(screen.getByTestId('zone-canvas'), { clientX: 80, clientY: 45 });
    expect(handlers.onSurfacePointerDown).toHaveBeenCalledWith({ x: 0.1, y: 0.9 });
  });

  it('draws stored geometry at its rotated display position', () => {
    renderCanvas({ rotation: 90 });
    const polygon = screen.getByTestId('zone-polygon-entrance-1');
    // Original (0.1, 0.1) -> display (0.9, 0.1) -> pixels (720, 45).
    expect(polygon.getAttribute('points')?.startsWith('720,45')).toBe(true);
  });
});
