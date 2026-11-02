import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Typography,
} from '@mui/material';

import type { Camera } from '../api/types';
import { useCameraMutations, useLivePlayback, useStartLivePlayback } from '../hooks/queries';
import { rotationFromConfiguration } from '../lib/videoRotation';
import type { Rotation } from '../lib/videoRotation';
import { LivePlayer } from './LivePlayer';
import { ErrorState, LoadingState } from './states';

/**
 * Live-view dialog for one camera.
 *
 * Opening it registers the camera's gateway path (idempotent) and then polls the
 * read-only status endpoint while the player is mounted. Closing it unmounts the player,
 * which closes the peer connection and deletes the WHEP session. When playback is not
 * configured or the gateway is unavailable, the dialog falls back honestly to stored
 * evidence instead of showing a broken player.
 *
 * The rotate controls change the camera's persisted `rotation` (saved through the existing
 * camera PATCH). The same value drives the live picture and the worker's detection, so a
 * sideways camera is fixed for both at once (D-72).
 */
export function LivePlaybackDialog({
  camera,
  onClose,
}: {
  camera: Camera | null;
  onClose: () => void;
}) {
  const cameraId = camera?.id ?? null;
  const live = useLivePlayback(cameraId);
  const start = useStartLivePlayback();
  const { mutate: startPlayback } = start;
  const { update } = useCameraMutations();

  const [rotation, setRotation] = useState<Rotation>(() =>
    rotationFromConfiguration(camera?.configuration),
  );
  const [rotationError, setRotationError] = useState<string | null>(null);

  useEffect(() => {
    if (cameraId !== null) startPlayback(cameraId);
  }, [cameraId, startPlayback]);

  const changeRotation = (next: Rotation) => {
    if (camera === null) return;
    const previous = rotation;
    setRotationError(null);
    setRotation(next);
    update.mutate(
      {
        id: camera.id,
        payload: { configuration: { ...(camera.configuration ?? {}), rotation: next } },
      },
      {
        onError: (caught) => {
          setRotation(previous);
          setRotationError(
            caught instanceof Error ? caught.message : 'Could not save the rotation.',
          );
        },
      },
    );
  };

  const info = live.data ?? start.data ?? null;
  const failure = live.error ?? start.error ?? null;
  const loading = cameraId !== null && info === null && failure === null;

  return (
    <Dialog open={camera !== null} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>Live view{camera !== null ? ` — ${camera.name}` : ''}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {camera === null ? null : (
            <>
              {loading && <LoadingState label="Connecting to the streaming gateway..." />}
              {!loading && failure !== null && <ErrorState error={failure} />}
              {info !== null && info.available && info.whep_url !== null && (
                <LivePlayer
                  key={info.whep_url}
                  whepUrl={info.whep_url}
                  rotation={rotation}
                  onRotate={changeRotation}
                />
              )}
              {info !== null && !(info.available && info.whep_url !== null) && (
                <Alert severity="info">
                  Live playback is unavailable
                  {info.detail !== null ? ` (${info.detail})` : ''}. Stored snapshots and clips
                  remain available from the event timeline. Check the gateway configuration and
                  network access in <code>docs/LIVE_PLAYBACK.md</code>.
                </Alert>
              )}
              {rotationError !== null && <Alert severity="error">{rotationError}</Alert>}
              <Typography variant="caption" color="text.secondary">
                Rotation is saved for this camera and also used to detect people and to store
                snapshots/clips, so straighten a sideways phone once and the picture, detection and
                recorded evidence are all fixed.
              </Typography>
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
