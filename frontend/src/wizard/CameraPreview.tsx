import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Alert, Box, CircularProgress, Stack, Typography } from '@mui/material';

import { useLivePlayback, useStartLivePlayback } from '../hooks/queries';
import { getContentRect } from './coordinates';
import type { Size } from './coordinates';
import { useWhep } from '../lib/whep';
import { useElementSize } from '../lib/useElementSize';
import { displayAspect, layoutVideo } from '../lib/videoRotation';
import type { Rotation } from '../lib/videoRotation';

export interface CameraPreviewProps {
  cameraId: number;
  /** Clockwise display rotation applied to the feed and the overlay geometry. */
  rotation?: Rotation;
  /** Aspect ratio (w/h) used to lay out the placeholder when no live preview exists. */
  fallbackAspect?: number;
  /** Rendered inside the visible video content rectangle; receives its pixel size. */
  children: (contentSize: Size) => ReactNode;
}

/**
 * Live camera preview with an overlay slot for the zone editor.
 *
 * When live playback is available the real WHEP video is shown; otherwise a clearly-labelled
 * **placeholder** is shown instead — it is never presented as the real camera feed. The
 * overlay is positioned exactly over the visible (rotated) video content (letterboxing
 * accounted for) so its coordinates map one-to-one to normalised display coordinates.
 *
 * The preview honours the camera's saved `rotation` so an operator can orient a sideways
 * camera correctly while drawing zones. The overlay reports display-normalised points; the
 * zone editor inverse-rotates them, so stored geometry stays in the original camera frame
 * (D-72/D-73).
 */
export function CameraPreview({
  cameraId,
  rotation = 0,
  fallbackAspect = 16 / 9,
  children,
}: CameraPreviewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const size = useElementSize(containerRef);
  const [videoSize, setVideoSize] = useState<Size | null>(null);

  const live = useLivePlayback(cameraId);
  const start = useStartLivePlayback();
  const { mutate: startPlayback } = start;

  useEffect(() => {
    startPlayback(cameraId);
  }, [cameraId, startPlayback]);

  const info = live.data ?? start.data ?? null;
  const whepUrl = info?.available && info.whep_url !== null ? info.whep_url : null;
  const live_available = whepUrl !== null;

  const { status, error } = useWhep(whepUrl, videoRef);

  const fallbackSource: Size = { width: fallbackAspect * 1000, height: 1000 };
  const contentSource = videoSize ?? fallbackSource;
  // A quarter turn swaps the displayed width/height, so the visible content rectangle and
  // the container aspect both describe the rotated frame.
  const displaySource: Size =
    rotation === 90 || rotation === 270
      ? { width: contentSource.height, height: contentSource.width }
      : contentSource;
  const containerAspect = displayAspect(rotation, fallbackSource);
  const content = getContentRect(size.width > 0 ? size : { width: 1, height: 1 }, displaySource);

  return (
    <Box>
      <Box
        ref={containerRef}
        sx={{
          position: 'relative',
          width: '100%',
          aspectRatio: `${containerAspect}`,
          bgcolor: 'common.black',
          borderRadius: 1,
          overflow: 'hidden',
        }}
        data-testid="camera-preview"
      >
        {live_available ? (
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            data-testid="camera-preview-video"
            data-rotation={rotation}
            onLoadedMetadata={(event) => {
              const element = event.currentTarget;
              if (element.videoWidth > 0 && element.videoHeight > 0) {
                setVideoSize({ width: element.videoWidth, height: element.videoHeight });
              }
            }}
            style={layoutVideo(rotation, size, contentSource)}
          />
        ) : (
          <Stack
            data-testid="camera-preview-placeholder"
            sx={{
              position: 'absolute',
              inset: 0,
              alignItems: 'center',
              justifyContent: 'center',
              p: 2,
              textAlign: 'center',
            }}
          >
            <Typography variant="subtitle2" color="text.secondary">
              Placeholder — no live preview available
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Draw zones on this canvas; they are stored as fractions of the frame, not screen
              pixels.
            </Typography>
          </Stack>
        )}

        {live_available && status === 'connecting' && (
          <Stack
            sx={{
              position: 'absolute',
              inset: 0,
              alignItems: 'center',
              justifyContent: 'center',
              bgcolor: 'rgba(0, 0, 0, 0.4)',
            }}
          >
            <CircularProgress size={22} color="inherit" />
          </Stack>
        )}

        <Box
          data-testid="camera-preview-overlay"
          sx={{
            position: 'absolute',
            left: `${content.left}px`,
            top: `${content.top}px`,
            width: `${content.width}px`,
            height: `${content.height}px`,
          }}
        >
          {children({
            width: Math.max(0, content.width),
            height: Math.max(0, content.height),
          })}
        </Box>
      </Box>

      {error !== null && (
        <Alert severity="warning" sx={{ mt: 1 }}>
          {error} Zone drawing still works on the placeholder geometry.
        </Alert>
      )}
    </Box>
  );
}
