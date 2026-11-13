import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import * as camerasApi from '../api/cameras';
import type { CameraCreatePayload, CameraUpdatePayload } from '../api/cameras';
import * as eventsApi from '../api/events';
import * as evidenceApi from '../api/evidence';
import * as healthApi from '../api/health';
import * as liveApi from '../api/live';
import * as monitoringApi from '../api/monitoring';
import * as settingsApi from '../api/settings';
import type { EventQuery, RetentionTarget, ReviewStatus } from '../api/types';

export const queryKeys = {
  health: ['health'] as const,
  cameras: ['cameras'] as const,
  monitoring: ['monitoring'] as const,
  events: (query: EventQuery) => ['events', query] as const,
  event: (eventId: number) => ['event', eventId] as const,
  settings: ['settings'] as const,
  live: (cameraId: number) => ['live', cameraId] as const,
};

export function useHealth() {
  return useQuery({ queryKey: queryKeys.health, queryFn: healthApi.getHealth });
}

export function useCameras(pollMs = 5_000) {
  return useQuery({
    queryKey: queryKeys.cameras,
    queryFn: camerasApi.listCameras,
    // The camera list carries the effective lifecycle status, which the backend projects
    // from worker heartbeats. Poll so a status change (e.g. a dead worker projected as
    // `disconnected`) becomes visible even when the realtime socket is unavailable.
    refetchInterval: pollMs,
  });
}

export function useMonitoringStatus(pollMs = 5_000) {
  return useQuery({
    queryKey: queryKeys.monitoring,
    queryFn: monitoringApi.getMonitoringStatus,
    refetchInterval: pollMs,
  });
}

export function useEvents(query: EventQuery) {
  return useQuery({
    queryKey: queryKeys.events(query),
    queryFn: () => eventsApi.listEvents(query),
  });
}

export function useEventDetail(eventId: number) {
  return useQuery({
    queryKey: queryKeys.event(eventId),
    queryFn: () => eventsApi.getEvent(eventId),
    enabled: Number.isFinite(eventId),
  });
}

export function useSettings() {
  return useQuery({ queryKey: queryKeys.settings, queryFn: settingsApi.getSettings });
}

/**
 * Live playback status for one camera, polled while a player is open. `cameraId` is
 * `null` when the dialog is closed, which disables the query.
 */
export function useLivePlayback(cameraId: number | null, pollMs = 3_000) {
  return useQuery({
    queryKey: queryKeys.live(cameraId ?? -1),
    queryFn: () => {
      if (cameraId === null) throw new Error('Live playback queried without a camera id.');
      return liveApi.getLivePlayback(cameraId);
    },
    enabled: cameraId !== null,
    refetchInterval: pollMs,
    retry: false,
  });
}

/** Register/refresh the gateway path. Idempotent; never starts monitoring. */
export function useStartLivePlayback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (cameraId: number) => liveApi.startLivePlayback(cameraId),
    onSuccess: (data, cameraId) => {
      queryClient.setQueryData(queryKeys.live(cameraId), data);
    },
  });
}

/**
 * Monitoring mutations. The dashboard never starts monitoring automatically — these only run
 * in response to an explicit operator action (FR-48 / project constraint).
 */
export function useMonitoringCommands() {
  const queryClient = useQueryClient();
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.monitoring });
    void queryClient.invalidateQueries({ queryKey: queryKeys.cameras });
  };

  return {
    start: useMutation({ mutationFn: monitoringApi.startMonitoring, onSuccess: invalidate }),
    pause: useMutation({ mutationFn: monitoringApi.pauseMonitoring, onSuccess: invalidate }),
    stop: useMutation({ mutationFn: monitoringApi.stopMonitoring, onSuccess: invalidate }),
  };
}

export function useCameraMutations() {
  const queryClient = useQueryClient();
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.cameras });
    void queryClient.invalidateQueries({ queryKey: queryKeys.monitoring });
  };

  return {
    create: useMutation({
      mutationFn: (payload: CameraCreatePayload) => camerasApi.createCamera(payload),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, payload }: { id: number; payload: CameraUpdatePayload }) =>
        camerasApi.updateCamera(id, payload),
      onSuccess: invalidate,
    }),
  };
}

export function useReviewEvent(eventId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ reviewStatus, note }: { reviewStatus: ReviewStatus; note?: string }) =>
      eventsApi.reviewEvent(eventId, reviewStatus, note),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.event(eventId) });
      void queryClient.invalidateQueries({ queryKey: ['events'] });
    },
  });
}

export function useEvidenceRetention(eventId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ evidenceId, target }: { evidenceId: number; target: RetentionTarget }) =>
      evidenceApi.updateEvidenceRetention(evidenceId, target),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.event(eventId) });
    },
  });
}
