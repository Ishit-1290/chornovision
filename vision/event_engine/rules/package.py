"""Package-left-at-entrance rule (EV-05; G §8.5, W §7.5).

The rule needs detector classes for packages/parcels (configurable via
``package_classes``). The Phase 4 YOLO detector is person-only, so this rule stays
inactive until a detector that emits those classes is configured — it never fabricates a
package observation.

A package event is opened only after the same track stays within
``package_stationary_tolerance`` of its anchor for ``package_stationary_seconds``. If it
moves materially the candidate/event is cancelled and the stationary timer restarts. If
the track disappears for longer than ``package_absence_tolerance_seconds`` the event is
completed (package removed from the scene).

Person association is not claimed. When a person is currently near the package the event
is marked low-certainty/possible-unattended (G §8.5); the fixed message already says
"appears" (W §8).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.events.types import Certainty, EventStatus, EventTransition, EventType
from app.events.zones import CameraRulesConfig, Point, Zone

from vision.event_engine.base import (
    ActiveEvent,
    BaseRule,
    EventIdFactory,
    certainty_from_confidence,
)
from vision.event_engine.geometry import (
    box_bottom_center,
    distance,
    in_zone,
    normalise_box,
)
from vision.event_engine.types import EngineFrame, EntityObservation


@dataclass
class _PackageState:
    anchor: Point
    stationary_since: float
    stationary_since_at: datetime
    last_seen: float
    event: ActiveEvent | None = None
    last_update: float | None = None


class PackageRule(BaseRule):
    """Detect a stationary package left within the configured entrance area."""

    event_types = (EventType.PACKAGE_LEFT_AT_ENTRANCE,)

    def __init__(
        self,
        *,
        camera_id: int,
        config: CameraRulesConfig,
        id_factory: EventIdFactory,
    ) -> None:
        super().__init__(camera_id=camera_id, config=config, id_factory=id_factory)
        self._zone: Zone | None = self.config.zone(self.config.package_zone_id)
        self._states: dict[int, _PackageState] = {}

    def reset(self) -> None:
        self._states.clear()

    def observe(self, frame: EngineFrame) -> list[EventTransition]:
        if self._zone is None:
            return []

        transitions: list[EventTransition] = []
        seen: set[int] = set()
        person_anchors = [self._anchor(track, frame) for track in frame.person_tracks()]

        for track in frame.tracks_of(self.config.package_classes):
            anchor = self._anchor(track, frame)
            if not in_zone(anchor, self._zone):
                continue
            seen.add(track.track_id)
            state = self._states.get(track.track_id)
            if state is None:
                state = _PackageState(
                    anchor=anchor,
                    stationary_since=frame.monotonic,
                    stationary_since_at=frame.observed_at,
                    last_seen=frame.monotonic,
                )
                self._states[track.track_id] = state
                continue

            state.last_seen = frame.monotonic
            if distance(anchor, state.anchor) > self.thresholds.package_stationary_tolerance:
                state.anchor = anchor
                state.stationary_since = frame.monotonic
                state.stationary_since_at = frame.observed_at
                if state.event is not None:
                    transitions.append(
                        self._cancel(state.event, frame.observed_at, reason="package_moved")
                    )
                    state.event = None
                continue

            duration = frame.monotonic - state.stationary_since
            person_nearby = any(
                distance(anchor, person) <= self.thresholds.package_person_proximity
                for person in person_anchors
            )

            if state.event is None:
                if duration < self.thresholds.package_stationary_seconds:
                    continue
                confidence = track.confidence if 0.0 < track.confidence <= 1.0 else None
                certainty = (
                    Certainty.LOW if person_nearby else certainty_from_confidence(confidence)
                )
                active, opened = self._open(
                    EventType.PACKAGE_LEFT_AT_ENTRANCE,
                    start_time=state.stationary_since_at,
                    trigger_time=frame.observed_at,
                    zone_id=self._zone.id,
                    zone_name=self._zone.name,
                    entity_id=track.track_id,
                    status=EventStatus.ACTIVE,
                    certainty=certainty,
                    confidence=confidence,
                    attributes={
                        "duration_seconds": round(duration, 3),
                        "stationary_threshold_seconds": (
                            self.thresholds.package_stationary_seconds
                        ),
                        "person_nearby": person_nearby,
                    },
                )
                state.event = active
                state.last_update = frame.monotonic
                transitions.append(opened)
                continue

            interval = self.thresholds.package_update_interval_seconds
            if state.last_update is None or frame.monotonic - state.last_update >= interval:
                state.last_update = frame.monotonic
                transitions.append(
                    self._update(
                        state.event,
                        frame.observed_at,
                        attributes={
                            "duration_seconds": round(duration, 3),
                            "person_nearby": person_nearby,
                        },
                    )
                )

        self._expire_absent(frame, seen, transitions)
        return transitions

    def on_stream_end(
        self, *, monotonic: float, observed_at: datetime, reason: str
    ) -> list[EventTransition]:
        del monotonic
        transitions: list[EventTransition] = []
        for state in self._states.values():
            if state.event is None:
                continue
            transition = self._finalise_on_stream_end(
                state.event, observed_at=observed_at, reason=reason
            )
            state.event = None
            if transition is not None:
                transitions.append(transition)
        self._states.clear()
        return transitions

    # -- helpers -----------------------------------------------------------------
    def _anchor(self, track: EntityObservation, frame: EngineFrame) -> Point:
        return box_bottom_center(normalise_box(track.bbox, frame.frame_width, frame.frame_height))

    def _expire_absent(
        self, frame: EngineFrame, seen: set[int], transitions: list[EventTransition]
    ) -> None:
        tolerance = self.thresholds.package_absence_tolerance_seconds
        for track_id in list(self._states):
            state = self._states[track_id]
            if track_id in seen:
                continue
            if frame.monotonic - state.last_seen <= tolerance:
                continue
            if state.event is not None:
                transitions.append(
                    self._resolve(
                        state.event,
                        frame.observed_at,
                        reason="package_removed",
                        attributes={
                            "duration_seconds": round(frame.monotonic - state.stationary_since, 3)
                        },
                    )
                )
            del self._states[track_id]

        limit = self.thresholds.max_tracked_entities
        if len(self._states) > limit:
            ordered = sorted(self._states.items(), key=lambda item: item[1].last_seen)
            for track_id, _state in ordered[: len(self._states) - limit]:
                del self._states[track_id]
