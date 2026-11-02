/** TypeScript mirrors of the backend API contracts (`backend/app/schemas`). */

export type CameraStatus =
  | 'configured'
  | 'connecting'
  | 'active'
  | 'degraded'
  | 'disconnected'
  | 'reconnecting'
  | 'stopped'
  | 'failed';

export type MonitoringState = 'stopped' | 'running' | 'paused';

export type EventType =
  | 'person_entering'
  | 'person_leaving'
  | 'room_occupancy_change'
  | 'crowd_forming'
  | 'door_open_too_long'
  | 'package_left_at_entrance'
  | 'person_motionless'
  | 'fall_from_bed';

export type EventStatus = 'candidate' | 'active' | 'completed' | 'uncertain' | 'cancelled';

export type ReviewStatus = 'unreviewed' | 'confirmed' | 'dismissed' | 'corrected';

export type EvidenceMediaType = 'snapshot' | 'clip';
export type EvidenceStatus = 'pending' | 'available' | 'failed';
export type RetentionStatus = 'retained' | 'protected' | 'deleted';
export type RetentionTarget = 'retained' | 'protected';

export type Severity = 'info' | 'warning' | 'critical';
export type Certainty = 'high' | 'medium' | 'low' | 'unknown';

export interface User {
  id: number;
  username: string;
  is_active: boolean;
  created_at: string;
}

export interface Camera {
  id: number;
  name: string;
  /** Already redacted by the backend (scheme/host/port/path only). */
  stream_reference: string;
  enabled: boolean;
  status: CameraStatus;
  configuration: Record<string, unknown>;
  /** True when an encrypted credential pair is stored; the pair itself is never sent. */
  has_stream_credentials: boolean;
  created_at: string;
  updated_at: string;
}

export type LivePlaybackState = 'unavailable' | 'connecting' | 'live' | 'disconnected' | 'error';

/** What the backend exposes for live playback; never contains a camera source or credentials. */
export interface LivePlaybackInfo {
  available: boolean;
  state: LivePlaybackState;
  protocol: 'webrtc' | null;
  path: string | null;
  whep_url: string | null;
  detail: string | null;
}

export interface MonitoringCameraState {
  id: number;
  name: string;
  enabled: boolean;
  status: CameraStatus;
}

export interface MonitoringStatus {
  state: MonitoringState;
  running: boolean;
  counts: Record<string, number>;
  cameras: MonitoringCameraState[];
}

export interface MonitoringCommandResponse {
  state: MonitoringState;
  affected: number;
}

export interface Evidence {
  id: number;
  event_id: number;
  media_type: EvidenceMediaType;
  status: EvidenceStatus;
  retention_status: RetentionStatus;
  relative_path: string | null;
  file_size_bytes: number | null;
  duration_seconds: number | null;
  captured_at: string;
  deleted_at: string | null;
  error: string | null;
}

export interface EventTransition {
  state_version: number;
  action: string;
  status: EventStatus;
  occurred_at: string;
  end_time: string | null;
  certainty: Certainty;
  confidence: number | null;
  message: string;
}

export interface EventListItem {
  id: number;
  event_id: string;
  camera_id: number;
  event_type: EventType;
  entity_id: number | null;
  zone_id: string | null;
  zone_name: string | null;
  start_time: string;
  trigger_time: string;
  last_updated_at: string;
  end_time: string | null;
  status: EventStatus;
  severity: Severity;
  certainty: Certainty;
  confidence: number | null;
  state_version: number;
  message: string;
  review_status: ReviewStatus;
}

export interface EventDetail extends EventListItem {
  attributes: Record<string, unknown>;
  evidence_refs: string[];
  rule_version: string | null;
  config_version: string | null;
  created_at: string;
  updated_at: string;
  evidence: Evidence[];
  transitions: EventTransition[];
}

export interface EventListResponse {
  items: EventListItem[];
  total: number;
  limit: number;
  offset: number;
}

export type EventOrder = 'asc' | 'desc';

export interface EventQuery {
  camera_id?: number;
  event_type?: EventType;
  status?: EventStatus;
  review_status?: ReviewStatus;
  since?: string;
  until?: string;
  order?: EventOrder;
  limit?: number;
  offset?: number;
}

export interface SystemSettings {
  evidence_enabled: boolean;
  evidence_retention_days: number;
  evidence_storage_limit_gb: number;
  evidence_retention_on_register: boolean;
  evidence_rolling_buffer_seconds: number;
  evidence_pre_event_seconds: number;
  evidence_post_event_seconds: number;
  evidence_snapshot_enabled: boolean;
  evidence_clip_fps: number;
  evidence_clip_max_frames: number;
  worker_heartbeat_timeout_seconds: number;
  live_playback_enabled: boolean;
  evidence_storage_used_bytes: number;
}

export interface HealthStatus {
  status: 'ok' | 'degraded';
  app_name: string;
  environment: string;
  database: 'ok' | 'unavailable';
}

export interface CameraHealthItem {
  id: number;
  status: CameraStatus;
}

export interface CameraHealthResponse {
  count: number;
  by_status: Record<string, number>;
  cameras: CameraHealthItem[];
}

export interface LoginResponse {
  user: User;
  expires_at: string;
}

export interface RealtimeEventMessage {
  type: 'event';
  event: {
    id: number;
    event_id: string;
    camera_id: number;
    event_type: EventType;
    status: EventStatus;
    review_status: ReviewStatus;
    trigger_time: string;
    message: string;
  };
}

export interface RealtimeCameraMessage {
  type: 'camera';
  camera: { id: number; status: CameraStatus };
}

export interface RealtimeMonitoringMessage {
  type: 'monitoring';
  state: MonitoringState;
  affected?: number;
}

export interface RealtimeEvidenceMessage {
  type: 'evidence';
  event_id: number;
  evidence: {
    id: number;
    retention_status: RetentionStatus;
    media_type?: EvidenceMediaType;
    status?: EvidenceStatus;
  };
}

export interface RealtimeReadyMessage {
  type: 'ready';
  user: { id: number; username: string };
}

export interface RealtimeErrorMessage {
  type: 'error';
  detail: string;
}

export type RealtimeMessage =
  | RealtimeEventMessage
  | RealtimeCameraMessage
  | RealtimeMonitoringMessage
  | RealtimeEvidenceMessage
  | RealtimeReadyMessage
  | RealtimeErrorMessage;
