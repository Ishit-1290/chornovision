/**
 * Dashboard WebSocket client with bounded exponential reconnection.
 *
 * The socket carries only lightweight notifications. Because the REST API is the source of
 * truth, a reconnect simply triggers a refetch by the caller — that is how updates missed
 * while the socket was down are recovered, rather than by buffering state in the browser.
 */

import type { RealtimeMessage } from './types';

export interface DashboardSocketOptions {
  url?: string;
  onMessage: (message: RealtimeMessage) => void;
  /** Called after every successful (re)connection; used to refetch missed updates. */
  onOpen?: () => void;
  onStatusChange?: (connected: boolean) => void;
  WebSocketImpl?: typeof WebSocket;
  minDelayMs?: number;
  maxDelayMs?: number;
}

export function defaultWebSocketUrl(): string {
  if (typeof window === 'undefined') return '/api/ws';
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/api/ws`;
}

export class DashboardSocket {
  private readonly url: string;
  private readonly onMessage: (message: RealtimeMessage) => void;
  private readonly onOpen?: () => void;
  private readonly onStatusChange?: (connected: boolean) => void;
  private readonly WebSocketImpl?: typeof WebSocket;
  private readonly minDelayMs: number;
  private readonly maxDelayMs: number;

  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private attempts = 0;
  private manuallyClosed = false;

  constructor(options: DashboardSocketOptions) {
    this.url = options.url ?? defaultWebSocketUrl();
    this.onMessage = options.onMessage;
    this.onOpen = options.onOpen;
    this.onStatusChange = options.onStatusChange;
    this.WebSocketImpl = options.WebSocketImpl;
    this.minDelayMs = options.minDelayMs ?? 1_000;
    this.maxDelayMs = options.maxDelayMs ?? 30_000;
  }

  connect(): void {
    if (this.socket !== null || this.manuallyClosed) return;

    const Impl = this.WebSocketImpl ?? WebSocket;
    const socket = new Impl(this.url);
    this.socket = socket;

    socket.onopen = () => {
      this.attempts = 0;
      this.onStatusChange?.(true);
      this.onOpen?.();
    };

    socket.onmessage = (event: MessageEvent) => {
      try {
        const parsed: unknown = JSON.parse(String(event.data));
        if (parsed && typeof parsed === 'object' && 'type' in parsed) {
          this.onMessage(parsed as RealtimeMessage);
        }
      } catch {
        // Malformed notifications are ignored; the REST API remains authoritative.
      }
    };

    socket.onclose = () => {
      this.socket = null;
      this.onStatusChange?.(false);
      if (!this.manuallyClosed) this.scheduleReconnect();
    };

    socket.onerror = () => {
      // Browsers follow an error with a close event; reconnection is handled there.
    };
  }

  close(): void {
    this.manuallyClosed = true;
    this.clearReconnectTimer();
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }

  private scheduleReconnect(): void {
    this.clearReconnectTimer();
    const delay = Math.min(this.maxDelayMs, this.minDelayMs * 2 ** this.attempts);
    this.attempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}
