import type {
  Camera,
  EventDetail,
  EventListItem,
  Evidence,
  LivePlaybackInfo,
  MonitoringStatus,
  SystemSettings,
  User,
} from '../api/types';

export const userFixture: User = {
  id: 1,
  username: 'admin',
  is_active: true,
  created_at: '2026-10-01T00:00:00Z',
};

export const cameraFixture: Camera = {
  id: 1,
  name: 'Front Door',
  stream_reference: 'rtsp://camera.local/stream',
  enabled: true,
  status: 'active',
  configuration: { zones: [] },
  has_stream_credentials: false,
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-02T00:00:00Z',
};

export const monitoringStatusFixture: MonitoringStatus = {
  state: 'stopped',
  running: false,
  counts: {},
  cameras: [],
};

export const evidenceFixture: Evidence = {
  id: 10,
  event_id: 1,
  media_type: 'snapshot',
  status: 'available',
  retention_status: 'retained',
  relative_path: 'events/1/snapshot-10.jpg',
  file_size_bytes: 2048,
  duration_seconds: null,
  captured_at: '2026-10-02T10:00:02Z',
  deleted_at: null,
  error: null,
};

export const eventListItemFixture: EventListItem = {
  id: 1,
  event_id: '11111111-1111-1111-1111-111111111111',
  camera_id: 1,
  event_type: 'person_entering',
  entity_id: 5,
  zone_id: null,
  zone_name: 'Entrance',
  start_time: '2026-10-02T10:00:00Z',
  trigger_time: '2026-10-02T10:00:00Z',
  last_updated_at: '2026-10-02T10:00:02Z',
  end_time: '2026-10-02T10:00:02Z',
  status: 'completed',
  severity: 'info',
  certainty: 'high',
  confidence: 0.91,
  state_version: 2,
  message: 'Person entered the monitored area.',
  review_status: 'unreviewed',
};

export const eventDetailFixture: EventDetail = {
  ...eventListItemFixture,
  attributes: { direction: 'in' },
  evidence_refs: ['snapshot:10'],
  rule_version: 'phase5-v1',
  config_version: 'cfg-1',
  created_at: '2026-10-02T10:00:00Z',
  updated_at: '2026-10-02T10:00:03Z',
  evidence: [evidenceFixture],
  transitions: [
    {
      state_version: 1,
      action: 'opened',
      status: 'active',
      occurred_at: '2026-10-02T10:00:00Z',
      end_time: null,
      certainty: 'high',
      confidence: 0.9,
      message: 'Person entering detected.',
    },
    {
      state_version: 2,
      action: 'resolved',
      status: 'completed',
      occurred_at: '2026-10-02T10:00:02Z',
      end_time: '2026-10-02T10:00:02Z',
      certainty: 'high',
      confidence: 0.91,
      message: 'Person entered the monitored area.',
    },
  ],
};

export const settingsFixture: SystemSettings = {
  evidence_enabled: true,
  evidence_retention_days: 30,
  evidence_storage_limit_gb: 25,
  evidence_retention_on_register: false,
  evidence_rolling_buffer_seconds: 15,
  evidence_pre_event_seconds: 5,
  evidence_post_event_seconds: 5,
  evidence_snapshot_enabled: true,
  evidence_clip_fps: 8,
  evidence_clip_max_frames: 200,
  worker_heartbeat_timeout_seconds: 15,
  live_playback_enabled: false,
  evidence_storage_used_bytes: 1_048_576,
};

export const livePlaybackFixture: LivePlaybackInfo = {
  available: true,
  state: 'connecting',
  protocol: 'webrtc',
  path: 'cv-cam-1',
  whep_url: 'http://gateway.example:8889/cv-cam-1/whep',
  detail: null,
};
