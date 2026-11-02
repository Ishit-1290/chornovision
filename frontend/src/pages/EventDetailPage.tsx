import { useState } from 'react';
import { Link as RouterLink, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Grid,
  Link,
  Stack,
  Step,
  StepLabel,
  Stepper,
  TextField,
  Typography,
} from '@mui/material';

import { useEventDetail, useEvidenceRetention, useReviewEvent } from '../hooks/queries';
import {
  CertaintyChip,
  EventStatusChip,
  EventTypeLabel,
  RetentionStatusChip,
  ReviewStatusChip,
  SeverityChip,
} from '../components/chips';
import { EmptyState, ErrorState, LoadingState } from '../components/states';
import { evidenceUrl } from '../api/evidence';
import { formatBytes, formatConfidence, formatDateTime, formatDuration } from '../lib/format';
import type { Evidence, ReviewStatus } from '../api/types';

function EvidenceCard({
  evidence,
  onToggle,
  busy,
}: {
  evidence: Evidence;
  onToggle: (evidence: Evidence) => void;
  busy: boolean;
}) {
  const available = evidence.status === 'available' && evidence.retention_status !== 'deleted';
  const protectedItem = evidence.retention_status === 'protected';

  return (
    <Card>
      <CardContent>
        <Stack spacing={1}>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
            <Typography variant="h3" sx={{ flexGrow: 1 }}>
              {evidence.media_type === 'snapshot' ? 'Snapshot' : 'Clip'}
            </Typography>
            <RetentionStatusChip status={evidence.retention_status} />
          </Stack>
          <Typography variant="body2" color="text.secondary">
            Captured {formatDateTime(evidence.captured_at)} ·{' '}
            {formatBytes(evidence.file_size_bytes)}
            {evidence.duration_seconds !== null &&
              ` · ${formatDuration(evidence.duration_seconds)}`}
          </Typography>

          {available && evidence.media_type === 'snapshot' && (
            <Box
              component="img"
              src={evidenceUrl(evidence.id)}
              alt="Event snapshot evidence"
              sx={{ width: '100%', borderRadius: 1, border: '1px solid', borderColor: 'divider' }}
            />
          )}
          {available && evidence.media_type === 'clip' && (
            <Box
              component="video"
              src={evidenceUrl(evidence.id)}
              controls
              sx={{ width: '100%', borderRadius: 1, border: '1px solid', borderColor: 'divider' }}
            />
          )}
          {!available && (
            <Alert severity={evidence.status === 'failed' ? 'error' : 'info'}>
              {evidence.status === 'failed'
                ? `Evidence capture failed${evidence.error ? `: ${evidence.error}` : '.'}`
                : evidence.retention_status === 'deleted'
                  ? 'This evidence has been deleted.'
                  : 'Evidence is still being processed.'}
            </Alert>
          )}

          <Box>
            <Button
              size="small"
              variant={protectedItem ? 'outlined' : 'contained'}
              color={protectedItem ? 'inherit' : 'secondary'}
              disabled={busy || evidence.retention_status === 'deleted'}
              onClick={() => onToggle(evidence)}
            >
              {protectedItem ? 'Release protection' : 'Protect from deletion'}
            </Button>
          </Box>
        </Stack>
      </CardContent>
    </Card>
  );
}

export function EventDetailPage() {
  const params = useParams();
  const eventId = Number(params.eventId);
  const event = useEventDetail(eventId);
  const review = useReviewEvent(eventId);
  const retention = useEvidenceRetention(eventId);
  const [note, setNote] = useState('');

  if (!Number.isFinite(eventId)) {
    return <ErrorState error={new Error('Invalid event id')} />;
  }

  if (event.isLoading) return <LoadingState />;
  if (event.isError) return <ErrorState error={event.error} onRetry={() => event.refetch()} />;
  if (!event.data) return <EmptyState>Event not found.</EmptyState>;

  const detail = event.data;

  const submitReview = (reviewStatus: ReviewStatus) => {
    review.mutate({ reviewStatus, note: note.trim() ? note.trim() : undefined });
  };

  const toggleEvidence = (evidence: Evidence) => {
    retention.mutate({
      evidenceId: evidence.id,
      target: evidence.retention_status === 'protected' ? 'retained' : 'protected',
    });
  };

  return (
    <Stack spacing={3}>
      <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
        <Typography variant="h1" sx={{ flexGrow: 1 }}>
          Event detail
        </Typography>
        <Link component={RouterLink} to="/events">
          Back to events
        </Link>
      </Stack>

      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
              <EventTypeLabel eventType={detail.event_type} />
              <EventStatusChip status={detail.status} />
              <SeverityChip severity={detail.severity} />
              <CertaintyChip certainty={detail.certainty} />
              <ReviewStatusChip status={detail.review_status} />
            </Stack>
            <Typography variant="h3">{detail.message}</Typography>
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                <Typography color="text.secondary" variant="overline">
                  Camera
                </Typography>
                <Typography>{detail.camera_id}</Typography>
              </Grid>
              <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                <Typography color="text.secondary" variant="overline">
                  Started
                </Typography>
                <Typography>{formatDateTime(detail.start_time)}</Typography>
              </Grid>
              <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                <Typography color="text.secondary" variant="overline">
                  Triggered
                </Typography>
                <Typography>{formatDateTime(detail.trigger_time)}</Typography>
              </Grid>
              <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                <Typography color="text.secondary" variant="overline">
                  Ended
                </Typography>
                <Typography>{formatDateTime(detail.end_time)}</Typography>
              </Grid>
              <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                <Typography color="text.secondary" variant="overline">
                  Zone
                </Typography>
                <Typography>{detail.zone_name ?? detail.zone_id ?? '—'}</Typography>
              </Grid>
              <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                <Typography color="text.secondary" variant="overline">
                  Confidence
                </Typography>
                <Typography>{formatConfidence(detail.confidence)}</Typography>
              </Grid>
              <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                <Typography color="text.secondary" variant="overline">
                  State version
                </Typography>
                <Typography>{detail.state_version}</Typography>
              </Grid>
              <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                <Typography color="text.secondary" variant="overline">
                  Rule / config
                </Typography>
                <Typography variant="body2">
                  {detail.rule_version ?? '—'} / {detail.config_version ?? '—'}
                </Typography>
              </Grid>
            </Grid>
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="h3" sx={{ mb: 2 }}>
            Review
          </Typography>
          <Typography color="text.secondary" variant="body2" sx={{ mb: 2 }}>
            Recording a decision does not alter the stored message, timestamps, lifecycle state, or
            confidence — the deterministic model output stays intact and auditable.
          </Typography>
          {review.isError && <ErrorState error={review.error} />}
          <Stack spacing={2}>
            <TextField
              label="Reviewer note (optional)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              multiline
              minRows={2}
              fullWidth
            />
            <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
              <Button
                variant="contained"
                color="success"
                disabled={review.isPending || detail.review_status === 'confirmed'}
                onClick={() => submitReview('confirmed')}
              >
                Confirm
              </Button>
              <Button
                variant="contained"
                color="error"
                disabled={review.isPending || detail.review_status === 'dismissed'}
                onClick={() => submitReview('dismissed')}
              >
                Dismiss
              </Button>
              <Button
                variant="contained"
                color="warning"
                disabled={review.isPending || detail.review_status === 'corrected'}
                onClick={() => submitReview('corrected')}
              >
                Mark corrected
              </Button>
              <Button
                variant="outlined"
                disabled={review.isPending || detail.review_status === 'unreviewed'}
                onClick={() => submitReview('unreviewed')}
              >
                Reset to unreviewed
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      <Box>
        <Typography variant="h2" sx={{ mb: 2 }}>
          Evidence
        </Typography>
        {retention.isError && (
          <Box sx={{ mb: 2 }}>
            <ErrorState error={retention.error} />
          </Box>
        )}
        {detail.evidence.length === 0 && (
          <EmptyState>No evidence was captured for this event.</EmptyState>
        )}
        <Grid container spacing={2}>
          {detail.evidence.map((evidence) => (
            <Grid key={evidence.id} size={{ xs: 12, md: 6 }}>
              <EvidenceCard
                evidence={evidence}
                onToggle={toggleEvidence}
                busy={retention.isPending}
              />
            </Grid>
          ))}
        </Grid>
      </Box>

      <Card>
        <CardContent>
          <Typography variant="h3" sx={{ mb: 2 }}>
            Transition history
          </Typography>
          {detail.transitions.length === 0 && <EmptyState>No transitions recorded.</EmptyState>}
          {detail.transitions.length > 0 && (
            <Stepper orientation="vertical" activeStep={detail.transitions.length}>
              {detail.transitions.map((transition) => (
                <Step key={transition.state_version} completed>
                  <StepLabel
                    optional={
                      <Typography variant="caption" color="text.secondary">
                        {formatDateTime(transition.occurred_at)} · v{transition.state_version} ·{' '}
                        {transition.action}
                      </Typography>
                    }
                  >
                    <Stack
                      direction="row"
                      spacing={1}
                      useFlexGap
                      sx={{ alignItems: 'center', flexWrap: 'wrap' }}
                    >
                      <EventStatusChip status={transition.status} />
                      <CertaintyChip certainty={transition.certainty} />
                      <span>{transition.message}</span>
                    </Stack>
                  </StepLabel>
                </Step>
              ))}
            </Stepper>
          )}
        </CardContent>
      </Card>
    </Stack>
  );
}
