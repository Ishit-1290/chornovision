import { Chip } from '@mui/material';
import type { ChipProps } from '@mui/material';

import { humanizeEventType, humanizeToken } from '../lib/format';
import type {
  CameraStatus,
  Certainty,
  EventStatus,
  EventType,
  ReviewStatus,
  RetentionStatus,
  Severity,
} from '../api/types';

type Color = ChipProps['color'];

const CAMERA_STATUS_COLOR: Record<CameraStatus, Color> = {
  configured: 'default',
  connecting: 'info',
  active: 'success',
  degraded: 'warning',
  disconnected: 'warning',
  reconnecting: 'info',
  stopped: 'default',
  failed: 'error',
};

const EVENT_STATUS_COLOR: Record<EventStatus, Color> = {
  candidate: 'info',
  active: 'warning',
  completed: 'success',
  uncertain: 'default',
  cancelled: 'default',
};

const REVIEW_STATUS_COLOR: Record<ReviewStatus, Color> = {
  unreviewed: 'default',
  confirmed: 'success',
  dismissed: 'error',
  corrected: 'warning',
};

const SEVERITY_COLOR: Record<Severity, Color> = {
  info: 'info',
  warning: 'warning',
  critical: 'error',
};

const CERTAINTY_COLOR: Record<Certainty, Color> = {
  high: 'success',
  medium: 'info',
  low: 'warning',
  unknown: 'default',
};

const RETENTION_COLOR: Record<RetentionStatus, Color> = {
  retained: 'default',
  protected: 'secondary',
  deleted: 'error',
};

export function CameraStatusChip({ status }: { status: CameraStatus }) {
  return <Chip size="small" label={humanizeToken(status)} color={CAMERA_STATUS_COLOR[status]} />;
}

export function EventStatusChip({ status }: { status: EventStatus }) {
  return <Chip size="small" label={humanizeToken(status)} color={EVENT_STATUS_COLOR[status]} />;
}

export function ReviewStatusChip({ status }: { status: ReviewStatus }) {
  return (
    <Chip
      size="small"
      variant="outlined"
      label={humanizeToken(status)}
      color={REVIEW_STATUS_COLOR[status]}
    />
  );
}

export function SeverityChip({ severity }: { severity: Severity }) {
  return (
    <Chip
      size="small"
      variant="outlined"
      label={humanizeToken(severity)}
      color={SEVERITY_COLOR[severity]}
    />
  );
}

export function CertaintyChip({ certainty }: { certainty: Certainty }) {
  return (
    <Chip
      size="small"
      variant="outlined"
      label={humanizeToken(certainty)}
      color={CERTAINTY_COLOR[certainty]}
    />
  );
}

export function RetentionStatusChip({ status }: { status: RetentionStatus }) {
  return <Chip size="small" label={humanizeToken(status)} color={RETENTION_COLOR[status]} />;
}

export function EventTypeLabel({ eventType }: { eventType: EventType }) {
  return <span>{humanizeEventType(eventType)}</span>;
}
