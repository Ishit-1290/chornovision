import { useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import {
  Button,
  Card,
  CardContent,
  FormControl,
  Grid,
  InputLabel,
  Link,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';

import { useCameras, useEvents } from '../hooks/queries';
import {
  EventStatusChip,
  EventTypeLabel,
  ReviewStatusChip,
  SeverityChip,
} from '../components/chips';
import { EmptyState, ErrorState, LoadingState } from '../components/states';
import { formatDateTime } from '../lib/format';
import type { EventOrder, EventQuery, EventStatus, EventType, ReviewStatus } from '../api/types';

const EVENT_TYPES: EventType[] = [
  'person_entering',
  'person_leaving',
  'room_occupancy_change',
  'crowd_forming',
  'door_open_too_long',
  'package_left_at_entrance',
  'person_motionless',
  'fall_from_bed',
];

const EVENT_STATUSES: EventStatus[] = [
  'candidate',
  'active',
  'completed',
  'uncertain',
  'cancelled',
];
const REVIEW_STATUSES: ReviewStatus[] = ['unreviewed', 'confirmed', 'dismissed', 'corrected'];

const PAGE_SIZE = 25;

export function EventsPage() {
  const [cameraId, setCameraId] = useState<string>('');
  const [eventType, setEventType] = useState<string>('');
  const [status, setStatus] = useState<string>('');
  const [reviewStatus, setReviewStatus] = useState<string>('');
  const [order, setOrder] = useState<EventOrder>('desc');
  const [since, setSince] = useState<string>('');
  const [page, setPage] = useState(0);

  const cameras = useCameras();

  const query: EventQuery = {
    camera_id: cameraId !== '' ? Number(cameraId) : undefined,
    event_type: eventType !== '' ? (eventType as EventType) : undefined,
    status: status !== '' ? (status as EventStatus) : undefined,
    review_status: reviewStatus !== '' ? (reviewStatus as ReviewStatus) : undefined,
    order,
    since: since !== '' ? new Date(since).toISOString() : undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  };

  const events = useEvents(query);

  const resetTo = (fn: () => void) => {
    fn();
    setPage(0);
  };

  const total = events.data?.total ?? 0;
  const rows = events.data?.items ?? [];

  return (
    <Stack spacing={3}>
      <Typography variant="h1">Events</Typography>

      <Card>
        <CardContent>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, sm: 6, md: 2 }}>
              <FormControl fullWidth size="small">
                <InputLabel id="camera-filter">Camera</InputLabel>
                <Select
                  labelId="camera-filter"
                  label="Camera"
                  value={cameraId}
                  onChange={(event) => resetTo(() => setCameraId(event.target.value))}
                >
                  <MenuItem value="">All</MenuItem>
                  {cameras.data?.map((camera) => (
                    <MenuItem key={camera.id} value={String(camera.id)}>
                      {camera.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 2 }}>
              <FormControl fullWidth size="small">
                <InputLabel id="type-filter">Type</InputLabel>
                <Select
                  labelId="type-filter"
                  label="Type"
                  value={eventType}
                  onChange={(event) => resetTo(() => setEventType(event.target.value))}
                >
                  <MenuItem value="">All</MenuItem>
                  {EVENT_TYPES.map((type) => (
                    <MenuItem key={type} value={type}>
                      <EventTypeLabel eventType={type} />
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 2 }}>
              <FormControl fullWidth size="small">
                <InputLabel id="status-filter">Status</InputLabel>
                <Select
                  labelId="status-filter"
                  label="Status"
                  value={status}
                  onChange={(event) => resetTo(() => setStatus(event.target.value))}
                >
                  <MenuItem value="">All</MenuItem>
                  {EVENT_STATUSES.map((value) => (
                    <MenuItem key={value} value={value}>
                      {value}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 2 }}>
              <FormControl fullWidth size="small">
                <InputLabel id="review-filter">Review</InputLabel>
                <Select
                  labelId="review-filter"
                  label="Review"
                  value={reviewStatus}
                  onChange={(event) => resetTo(() => setReviewStatus(event.target.value))}
                >
                  <MenuItem value="">All</MenuItem>
                  {REVIEW_STATUSES.map((value) => (
                    <MenuItem key={value} value={value}>
                      {value}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 2 }}>
              <TextField
                label="Since"
                type="datetime-local"
                size="small"
                fullWidth
                value={since}
                onChange={(event) => resetTo(() => setSince(event.target.value))}
                slotProps={{ inputLabel: { shrink: true } }}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 2 }}>
              <FormControl fullWidth size="small">
                <InputLabel id="order-filter">Order</InputLabel>
                <Select
                  labelId="order-filter"
                  label="Order"
                  value={order}
                  onChange={(event) => resetTo(() => setOrder(event.target.value as EventOrder))}
                >
                  <MenuItem value="desc">Newest first</MenuItem>
                  <MenuItem value="asc">Oldest first</MenuItem>
                </Select>
              </FormControl>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          {events.isLoading && <LoadingState />}
          {events.isError && <ErrorState error={events.error} onRetry={() => events.refetch()} />}
          {events.data && rows.length === 0 && (
            <EmptyState>No events match the current filters.</EmptyState>
          )}
          {rows.length > 0 && (
            <>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Trigger time</TableCell>
                    <TableCell>Type</TableCell>
                    <TableCell>Severity</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell>Review</TableCell>
                    <TableCell>Message</TableCell>
                    <TableCell align="right" />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((event) => (
                    <TableRow key={event.id} hover>
                      <TableCell>{formatDateTime(event.trigger_time)}</TableCell>
                      <TableCell>
                        <EventTypeLabel eventType={event.event_type} />
                      </TableCell>
                      <TableCell>
                        <SeverityChip severity={event.severity} />
                      </TableCell>
                      <TableCell>
                        <EventStatusChip status={event.status} />
                      </TableCell>
                      <TableCell>
                        <ReviewStatusChip status={event.review_status} />
                      </TableCell>
                      <TableCell sx={{ maxWidth: 420 }}>{event.message}</TableCell>
                      <TableCell align="right">
                        <Button component={RouterLink} to={`/events/${event.id}`} size="small">
                          Details
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <TablePagination
                component="div"
                count={total}
                page={page}
                onPageChange={(_event, next) => setPage(next)}
                rowsPerPage={PAGE_SIZE}
                rowsPerPageOptions={[PAGE_SIZE]}
                onRowsPerPageChange={() => {}}
              />
            </>
          )}
        </CardContent>
      </Card>

      <Link component={RouterLink} to="/">
        Back to overview
      </Link>
    </Stack>
  );
}
