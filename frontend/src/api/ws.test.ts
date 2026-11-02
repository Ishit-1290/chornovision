import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DashboardSocket, defaultWebSocketUrl } from './ws';
import type { RealtimeMessage } from './types';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  url: string;
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
    this.onclose?.();
  }

  emitMessage(data: unknown): void {
    this.onmessage?.({ data });
  }
}

function factory(): typeof WebSocket {
  return FakeWebSocket as unknown as typeof WebSocket;
}

describe('DashboardSocket', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('parses JSON notifications and ignores malformed frames', () => {
    const onMessage = vi.fn<(message: RealtimeMessage) => void>();
    const socket = new DashboardSocket({ onMessage, WebSocketImpl: factory() });
    socket.connect();

    const instance = FakeWebSocket.instances[0];
    instance.emitMessage(JSON.stringify({ type: 'camera', camera: { id: 1, status: 'active' } }));
    expect(onMessage).toHaveBeenCalledWith({
      type: 'camera',
      camera: { id: 1, status: 'active' },
    });

    instance.emitMessage('not json');
    instance.emitMessage(JSON.stringify({ noType: true }));
    expect(onMessage).toHaveBeenCalledTimes(1);
  });

  it('signals open and resets backoff after a successful connection', () => {
    const onOpen = vi.fn();
    const onStatusChange = vi.fn();
    const socket = new DashboardSocket({
      onMessage: vi.fn(),
      onOpen,
      onStatusChange,
      WebSocketImpl: factory(),
    });
    socket.connect();

    FakeWebSocket.instances[0].onopen?.();
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onStatusChange).toHaveBeenLastCalledWith(true);
  });

  it('reconnects with backoff after an unexpected close', () => {
    const onStatusChange = vi.fn();
    const socket = new DashboardSocket({
      onMessage: vi.fn(),
      onStatusChange,
      WebSocketImpl: factory(),
      minDelayMs: 10,
      maxDelayMs: 100,
    });
    socket.connect();
    expect(FakeWebSocket.instances).toHaveLength(1);

    FakeWebSocket.instances[0].onclose?.();
    expect(onStatusChange).toHaveBeenLastCalledWith(false);

    vi.advanceTimersByTime(10);
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it('stops reconnecting after an explicit close', () => {
    const socket = new DashboardSocket({
      onMessage: vi.fn(),
      WebSocketImpl: factory(),
      minDelayMs: 10,
    });
    socket.connect();
    socket.close();
    expect(FakeWebSocket.instances[0].closed).toBe(true);

    vi.advanceTimersByTime(1_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('derives the default URL from the current location', () => {
    expect(defaultWebSocketUrl()).toBe(`ws://${window.location.host}/api/ws`);
  });
});
