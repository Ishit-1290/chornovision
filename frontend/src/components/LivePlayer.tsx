import { useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Stack,
  Tooltip,
} from '@mui/material';
import Rotate90DegreesCcwIcon from '@mui/icons-material/Rotate90DegreesCcw';
import Rotate90DegreesCwIcon from '@mui/icons-material/Rotate90DegreesCw';

import { useWhep } from '../lib/whep';
import type { WhepStatus } from '../lib/whep';
import { useElementSize } from '../lib/useElementSize';
import {
  DEFAULT_SOURCE,
  displayAspect,
  layoutVideo,
  rotateCCW,
  rotateCW,
} from '../lib/videoRotation';
import type { Rotation } from '../lib/videoRotation';
import type { Size } from '../lib/useElementSize';

/**
 * Minimal WHEP player for MediaMTX, rendered over the shared {@link useWhep} connection.
 *
 * The player only ever talks to the gateway's browser-facing WHEP URL. It never sees a camera
 * source URL or camera credentials, and it sends no cookies because the gateway is a separate
 * origin.
 *
 * A sideways feed can be straightened with the rotate controls. Rotation is a **per-camera
 * setting**: the parent passes the current value and an `onRotate` handler that persists it,
 * so the same value drives both this view and detection (D-72). With no handler the controls
 * are shown but disabled.
 */
const STATUS_LABEL: Record<WhepStatus, string> = {
  connecting: 'Connecting...',
  live: 'Live',
  disconnected: 'Disconnected',
  error: 'Playback error',
};

const STATUS_COLOR: Record<WhepStatus, 'default' | 'success' | 'warning' | 'error'> = {
  connecting: 'default',
  live: 'success',
  disconnected: 'warning',
  error: 'error',
};

export function LivePlayer({
  whepUrl,
  rotation = 0,
  onRotate,
}: {
  whepUrl: string;
  /** The camera's persisted detection rotation, in degrees clockwise. */
  rotation?: Rotation;
  /** Persist a new rotation. When omitted the rotate controls are disabled. */
  onRotate?: (rotation: Rotation) => void;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const { status, error, retry } = useWhep(whepUrl, videoRef);

  const [source, setSource] = useState<Size>(DEFAULT_SOURCE);
  const container = useElementSize(frameRef);
  const canRotate = onRotate !== undefined;

  return (
    <Box>
      <Box
        ref={frameRef}
        data-testid="live-player-frame"
        sx={{
          position: 'relative',
          width: '100%',
          aspectRatio: `${displayAspect(rotation, source)}`,
          maxHeight: '62vh',
          bgcolor: 'common.black',
          borderRadius: 1,
          overflow: 'hidden',
        }}
      >
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          data-testid="live-player-video"
          data-rotation={rotation}
          onLoadedMetadata={(event) => {
            const element = event.currentTarget;
            if (element.videoWidth > 0 && element.videoHeight > 0) {
              setSource({ width: element.videoWidth, height: element.videoHeight });
            }
          }}
          style={layoutVideo(rotation, container, source)}
        />
        {status === 'connecting' && (
          <Stack
            sx={{
              position: 'absolute',
              inset: 0,
              alignItems: 'center',
              justifyContent: 'center',
              bgcolor: 'rgba(0, 0, 0, 0.55)',
              color: 'common.white',
              p: 2,
            }}
          >
            <CircularProgress size={24} color="inherit" />
          </Stack>
        )}
      </Box>

      <Stack direction="row" spacing={1} sx={{ mt: 1, alignItems: 'center', flexWrap: 'wrap' }}>
        <Chip size="small" color={STATUS_COLOR[status]} label={STATUS_LABEL[status]} />
        {(status === 'error' || status === 'disconnected') && (
          <Button size="small" onClick={retry}>
            Try again
          </Button>
        )}

        <Box sx={{ flexGrow: 1 }} />

        <Tooltip title={canRotate ? 'Rotate 90° left' : 'Rotation is not available here'}>
          <span>
            <IconButton
              size="small"
              aria-label="Rotate left"
              disabled={!canRotate}
              onClick={() => onRotate?.(rotateCCW(rotation))}
            >
              <Rotate90DegreesCcwIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
        <Chip size="small" variant="outlined" label={`${rotation}°`} />
        <Tooltip title={canRotate ? 'Rotate 90° right' : 'Rotation is not available here'}>
          <span>
            <IconButton
              size="small"
              aria-label="Rotate right"
              disabled={!canRotate}
              onClick={() => onRotate?.(rotateCW(rotation))}
            >
              <Rotate90DegreesCwIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
        {canRotate && (
          <Button size="small" disabled={rotation === 0} onClick={() => onRotate?.(0)}>
            Reset
          </Button>
        )}
      </Stack>

      {status === 'disconnected' && (
        <Alert severity="warning" sx={{ mt: 1 }}>
          The stream disconnected. Playback may recover automatically; use “Try again” if it does
          not.
        </Alert>
      )}
      {error !== null && (
        <Alert severity="error" sx={{ mt: 1 }}>
          {error}
        </Alert>
      )}
    </Box>
  );
}
