"""Entry/exit rule (EV-01, EV-02; G §8.1, §8.2).

A ``person_entering`` or ``person_leaving`` event is produced only when a tracked
person's anchor point crosses the entrance boundary in the configured direction. The
anchor is the bottom-centre of the bounding box (a stable "feet" point) and the crossing
must be confirmed on ``boundary_confirm_frames`` consecutive observations to suppress
single-frame jitter.

Presence is never an entrance (G §8.1): a track first observed on either side of the
boundary establishes its starting side without emitting anything. A track that simply
disappears from view does not emit a leaving event, because leaving requires an observed
outward crossing (G §8.2).

Both events are **instantaneous**: the guideline lifecycle explicitly permits a boundary
crossing to be created and completed immediately (G §7), which also keeps deduplication
explicit — one crossing produces one opened + one resolved transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.events.types import (
    EventStatus,
    EventTransition,
    EventType,
)
from app.events.zones import CameraRulesConfig, Zone

from vision.event_engine.base import (
    BaseRule,
    EventIdFactory,
    certainty_from_confidence,
)
from vision.event_engine.geometry import (
    boundary_side,
    box_bottom_center,
    normalise_box,
)
from vision.event_engine.types import EngineFrame, EntityObservation

#: How long a track's state is kept after it was last seen (frames), so a genuine
#: crossing across a brief occlusion is still detected.
_STATE_TTL_FRAMES = 300


@dataclass
class _TrackState:
    side: int
    pending_side: int
    pending_count: int
    pending_since_at: datetime
    last_seen_frame: int
    last_crossing_monotonic: float | None = None


class BoundaryCrossingRule(BaseRule):
    """Detect confirmed inward/outward boundary crossings."""

    event_types = (EventType.PERSON_ENTERING, EventType.PERSON_LEAVING)

    def __init__(
        self,
        *,
        camera_id: int,
        config: CameraRulesConfig,
        id_factory: EventIdFactory,
    ) -> None:
        super().__init__(camera_id=camera_id, config=config, id_factory=id_factory)
        self._zone: Zone | None = self.config.zone(self.config.entrance_zone_id)
        self._state: dict[int, _TrackState] = {}
        self._frame_index = 0

    def reset(self) -> None:
        self._state.clear()
        self._frame_index = 0

    def observe(self, frame: EngineFrame) -> list[EventTransition]:
        self._frame_index += 1
        boundary = self._zone.boundary if self._zone is not None else None
        if self._zone is None or boundary is None:
            return []

        transitions: list[EventTransition] = []
        seen: set[int] = set()
        for track in frame.person_tracks():
            anchor = box_bottom_center(
                normalise_box(track.bbox, frame.frame_width, frame.frame_height)
            )
            side = boundary_side(anchor, boundary, self.thresholds.boundary_side_epsilon)
            if side == 0:
                continue  # ambiguous (on the line); wait for a clearer frame
            seen.add(track.track_id)
            state = self._state.get(track.track_id)
            if state is None:
                # First observation: presence, not a crossing.
                self._state[track.track_id] = _TrackState(
                    side=side,
                    pending_side=side,
                    pending_count=1,
                    pending_since_at=frame.observed_at,
                    last_seen_frame=self._frame_index,
                )
                continue

            state.last_seen_frame = self._frame_index
            if state.side == side:
                # Already on this side: reset any half-observed pending crossing.
                state.pending_side = side
                state.pending_count = 1
                continue

            if state.pending_side == side:
                state.pending_count += 1
            else:
                state.pending_side = side
                state.pending_count = 1
                state.pending_since_at = frame.observed_at

            if state.pending_count < self.thresholds.boundary_confirm_frames:
                continue

            state.side = side
            state.pending_count = 0
            cooldown = self.thresholds.boundary_cooldown_seconds
            if (
                state.last_crossing_monotonic is not None
                and frame.monotonic - state.last_crossing_monotonic < cooldown
            ):
                # Suppress a rapid re-cross (tracker jitter) without losing the side.
                continue
            state.last_crossing_monotonic = frame.monotonic
            transitions.extend(self._emit_crossing(frame, track, state, side))

        self._prune(seen)
        return transitions

    # -- helpers -----------------------------------------------------------------
    def _emit_crossing(
        self,
        frame: EngineFrame,
        track: EntityObservation,
        state: _TrackState,
        side: int,
    ) -> list[EventTransition]:
        assert self._zone is not None  # guarded by observe()
        event_type = EventType.PERSON_ENTERING if side == 1 else EventType.PERSON_LEAVING
        confidence = track.confidence if 0.0 < track.confidence <= 1.0 else None
        active, opened = self._open(
            event_type,
            start_time=state.pending_since_at,
            trigger_time=frame.observed_at,
            zone_id=self._zone.id,
            zone_name=self._zone.name,
            entity_id=track.track_id,
            status=EventStatus.ACTIVE,
            certainty=certainty_from_confidence(confidence),
            confidence=confidence,
            attributes={
                "direction": "inward" if side == 1 else "outward",
                "confirm_frames": self.thresholds.boundary_confirm_frames,
            },
        )
        resolved = self._resolve(active, frame.observed_at, reason="boundary_crossing_confirmed")
        return [opened, resolved]

    def _prune(self, seen: set[int]) -> None:
        stale = [
            track_id
            for track_id, state in self._state.items()
            if track_id not in seen
            and self._frame_index - state.last_seen_frame > _STATE_TTL_FRAMES
        ]
        for track_id in stale:
            del self._state[track_id]
        limit = self.thresholds.max_tracked_entities
        if len(self._state) > limit:
            ordered = sorted(self._state.items(), key=lambda item: item[1].last_seen_frame)
            for track_id, _state in ordered[: len(self._state) - limit]:
                del self._state[track_id]
