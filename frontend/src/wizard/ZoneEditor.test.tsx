import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import { ZoneEditor } from './ZoneEditor';
import type { WizardZone } from './wizardTypes';
import { renderWithProviders } from '../test/render';
import * as liveApi from '../api/live';

vi.mock('../api/live', () => ({
  getLivePlayback: vi.fn(),
  startLivePlayback: vi.fn(),
}));

const unavailable = {
  available: false,
  state: 'unavailable' as const,
  protocol: null,
  path: null,
  whep_url: null,
  detail: 'not configured',
};

const entranceZone: WizardZone = {
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

function Harness({
  initialZones,
  roles,
  onChange,
}: {
  initialZones: WizardZone[];
  roles: Parameters<typeof ZoneEditor>[0]['requiredRoles'];
  onChange?: (zones: WizardZone[]) => void;
}) {
  const [zones, setZones] = useState<WizardZone[]>(initialZones);
  const [selected, setSelected] = useState<string | null>(initialZones[0]?.id ?? null);
  const [rotation, setRotation] = useState<Parameters<typeof ZoneEditor>[0]['rotation']>(0);
  return (
    <ZoneEditor
      cameraId={1}
      zones={zones}
      requiredRoles={roles}
      selectedZoneId={selected}
      zoneErrors={{}}
      rotation={rotation}
      onRotate={setRotation}
      onChange={(next) => {
        setZones(next);
        onChange?.(next);
      }}
      onSelectZone={setSelected}
    />
  );
}

describe('ZoneEditor', () => {
  beforeEach(() => {
    vi.mocked(liveApi.startLivePlayback).mockResolvedValue(unavailable);
    vi.mocked(liveApi.getLivePlayback).mockResolvedValue(unavailable);
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true,
      get: () => 800,
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get: () => 450,
    });
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      right: 800,
      bottom: 450,
      width: 800,
      height: 450,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('creates a polygon zone by drawing points and finishing', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(<Harness initialZones={[]} roles={['room_zone_id']} onChange={onChange} />);

    await user.click(screen.getByRole('button', { name: 'Add zone' }));

    const canvas = screen.getByTestId('zone-canvas');
    fireEvent.pointerDown(canvas, { clientX: 80, clientY: 45 });
    fireEvent.pointerDown(canvas, { clientX: 720, clientY: 80 });
    fireEvent.pointerDown(canvas, { clientX: 400, clientY: 400 });

    await user.click(screen.getByRole('button', { name: 'Finish zone' }));

    await screen.findByText(/Room — Room/);
    const zones = onChange.mock.calls.at(-1)?.[0] as WizardZone[];
    expect(zones).toHaveLength(1);
    expect(zones[0].kind).toBe('room');
    expect(zones[0].polygon).toHaveLength(3);
    expect(zones[0].polygon[0]).toEqual({ x: 0.1, y: 0.1 });
  });

  it('undoes the last drawn point', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness initialZones={[]} roles={['room_zone_id']} />);
    await user.click(screen.getByRole('button', { name: 'Add zone' }));

    const canvas = screen.getByTestId('zone-canvas');
    fireEvent.pointerDown(canvas, { clientX: 80, clientY: 80 });
    fireEvent.pointerDown(canvas, { clientX: 720, clientY: 80 });
    expect(screen.getByText(/2 point\(s\) added/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Undo point' }));
    expect(screen.getByText(/1 point\(s\) added/)).toBeInTheDocument();
  });

  it('deletes a zone from the list', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(
      <Harness initialZones={[entranceZone]} roles={['entrance_zone_id']} onChange={onChange} />,
    );

    const list = screen.getByTestId('zone-list');
    await user.click(within(list).getByLabelText('Delete zone Entrance'));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('lets the user pick the interior side of an entrance boundary', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness initialZones={[entranceZone]} roles={['entrance_zone_id']} />);

    expect(screen.getByRole('button', { name: 'Interior on the left' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await user.click(screen.getByRole('button', { name: 'Interior on the right' }));
    expect(screen.getByRole('button', { name: 'Interior on the right' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('rotates the preview view and resets it', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness initialZones={[]} roles={['room_zone_id']} />);

    expect(screen.getByText('View 0°')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Rotate view right' }));
    expect(screen.getByText('View 90°')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Rotate view left' }));
    expect(screen.getByText('View 0°')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Rotate view right' }));
    await user.click(screen.getByRole('button', { name: 'Reset view' }));
    expect(screen.getByText('View 0°')).toBeInTheDocument();
  });
});
