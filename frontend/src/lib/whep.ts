import { useEffect, useState } from 'react';
import type { RefObject } from 'react';

/**
 * Shared WHEP (WebRTC-HTTP Egress Protocol) connection logic for MediaMTX.
 *
 * Flow (non-trickle ICE, MediaMTX v1.21.x):
 *   1. create a recvonly offer and wait until ICE gathering completes;
 *   2. POST the offer SDP to the WHEP URL, expecting 201 + an SDP answer;
 *   3. apply the answer and render the inbound tracks into the supplied video element;
 *   4. on unmount/URL change, DELETE the session resource named by the `Location` header.
 *
 * The hook only ever talks to the gateway's browser-facing WHEP URL. It never sees a camera
 * source URL or camera credentials, and it sends no cookies (`credentials: omit`) because the
 * gateway is a separate origin. The caller owns the `<video>` element and passes its ref.
 */
export type WhepStatus = 'connecting' | 'live' | 'disconnected' | 'error';

export interface WhepConnection {
  status: WhepStatus;
  error: string | null;
  /** Tear down and reconnect (used by an explicit "Try again" action). */
  retry: () => void;
}

const ICE_GATHERING_TIMEOUT_MS = 3_000;

function waitForIceGathering(peer: RTCPeerConnection, timeoutMs = ICE_GATHERING_TIMEOUT_MS) {
  if (peer.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise<void>((resolve) => {
    const finish = () => {
      peer.removeEventListener('icegatheringstatechange', onChange);
      clearTimeout(timer);
      resolve();
    };
    const onChange = () => {
      if (peer.iceGatheringState === 'complete') finish();
    };
    peer.addEventListener('icegatheringstatechange', onChange);
    const timer = setTimeout(finish, timeoutMs);
  });
}

export function useWhep(
  whepUrl: string | null,
  videoRef: RefObject<HTMLVideoElement | null>,
): WhepConnection {
  const [status, setStatus] = useState<WhepStatus>('connecting');
  const [error, setError] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    // No gateway URL (e.g. live playback unavailable): do not attempt a connection.
    if (whepUrl === null) return;
    let cancelled = false;
    let peer: RTCPeerConnection | null = null;
    let sessionUrl: string | null = null;
    // Capture the node once so the cleanup uses a stable reference.
    const video = videoRef.current;

    const deleteSession = () => {
      if (sessionUrl === null) return;
      const url = sessionUrl;
      sessionUrl = null;
      void fetch(url, { method: 'DELETE', credentials: 'omit' }).catch(() => undefined);
    };

    const connect = async () => {
      try {
        if (typeof RTCPeerConnection === 'undefined') {
          throw new Error('This browser does not support WebRTC playback.');
        }
        const pc = new RTCPeerConnection({ iceServers: [] });
        peer = pc;

        pc.addTransceiver('video', { direction: 'recvonly' });
        pc.addTransceiver('audio', { direction: 'recvonly' });

        pc.ontrack = (event) => {
          if (video === null) return;
          const [stream] = event.streams;
          if (stream !== undefined) {
            video.srcObject = stream;
            void video.play().catch(() => undefined);
          }
        };
        pc.onconnectionstatechange = () => {
          if (cancelled) return;
          switch (pc.connectionState) {
            case 'connected':
              setStatus('live');
              break;
            case 'disconnected':
              setStatus('disconnected');
              break;
            case 'failed':
              setStatus('error');
              setError('The media connection failed. The camera or gateway may be offline.');
              break;
            default:
              break;
          }
        };

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await waitForIceGathering(pc);
        if (cancelled) return;

        const response = await fetch(whepUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/sdp' },
          body: pc.localDescription?.sdp ?? '',
          credentials: 'omit',
        });
        if (!response.ok) {
          throw new Error(`The streaming gateway rejected playback (HTTP ${response.status}).`);
        }

        const location = response.headers.get('Location');
        if (location !== null) {
          sessionUrl = new URL(location, whepUrl).toString();
        }
        if (cancelled) {
          deleteSession();
          return;
        }

        const answer = await response.text();
        await pc.setRemoteDescription({ type: 'answer', sdp: answer });
      } catch (caught) {
        if (cancelled) return;
        setStatus('error');
        setError(caught instanceof Error ? caught.message : 'Live playback failed.');
      }
    };

    void connect();

    return () => {
      cancelled = true;
      if (peer !== null) {
        peer.close();
        peer = null;
      }
      if (video !== null) video.srcObject = null;
      deleteSession();
    };
  }, [whepUrl, generation, videoRef]);

  const retry = () => {
    setStatus('connecting');
    setError(null);
    setGeneration((value) => value + 1);
  };

  return { status, error, retry };
}
