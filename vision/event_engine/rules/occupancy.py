"""Occupancy and crowd rules (EV-03; G §8.3, W §7.3).

Two related but distinct event types are produced (D-10):

* ``room_occupancy_change`` — an instantaneous, point-in-time occupancy update for the
  configured room zone. Temporary detection loss does not flicker the count because a
  track stays "retained" for ``occupancy_retention_seconds`` after it was last seen in
  the zone (G §8.3):
  the smoothing is a documented track-retention policy, not a frame-to-frame count.
  A change is only reported once it has persisted for ``occupancy_persistence_seconds``.
* ``crowd_forming`` — a persistent event opened when retained occupancy stays at or above
  ``crowd_occupancy_threshold`` for ``crowd_persistence_seconds``, updated while it
  holds, and completed after occupancy drops below ``threshold - hysteresis`` for
  ``crowd_release_seconds``.

The engine never claims precise crowd density (G §8.3): it reports the retained tracked
count and the applicable threshold, and carries uncertainty categorically.
"""

from __future__ import annotations

from datetime import datetime

from app.events.types import EventStatus, EventTransition, EventType
from app.events.zones import CameraRulesConfig, Zone

from vision.event_engine.base import (
    ActiveEvent,
    BaseRule,
    EventIdFactory,
    certainty_from_confidence,
    confidence_from_tracks,
)
from vision.event_engine.geometry import box_bottom_center, in_zone, normalise_box
from vision.event_engine.types import EngineFrame, EntityObservation


class OccupancyRule(BaseRule):
    """Track retained room occupancy and sustained crowd formation."""

    event_types = (EventType.ROOM_OCCUPANCY_CHANGE, EventType.CROWD_FORMING)

    def __init__(
        self,
        *,
        camera_id: int,
        config: CameraRulesConfig,
        id_factory: EventIdFactory,
    ) -> None:
        super().__init__(camera_id=camera_id, config=config, id_factory=id_factory)
        self._zone: Zone | None = self.config.zone(self.config.room_zone_id)
        self._retained: dict[int, float] = {}
        self._last_reported: int | None = None
        self._pending_count: int | None = None
        self._pending_since: float | None = None
        self._crowd_event: ActiveEvent | None = None
        self._crowd_high_since: float | None = None
        self._crowd_high_since_at: datetime | None = None
        self._crowd_low_since: float | None = None

    def reset(self) -> None:
        self._retained.clear()
        self._last_reported = None
        self._pending_count = None
        self._pending_since = None
        self._crowd_event = None
        self._crowd_high_since = None
        self._crowd_high_since_at = None
        self._crowd_low_since = None

    def observe(self, frame: EngineFrame) -> list[EventTransition]:
        if self._zone is None:
            return []

        in_zone_tracks: list[EntityObservation] = []
        for track in frame.person_tracks():
            anchor = box_bottom_center(
                normalise_box(track.bbox, frame.frame_width, frame.frame_height)
            )
            if in_zone(anchor, self._zone):
                in_zone_tracks.append(track)
                self._retained[track.track_id] = frame.monotonic

        retention = self.thresholds.occupancy_retention_seconds
        for track_id in list(self._retained):
            if frame.monotonic - self._retained[track_id] > retention:
                del self._retained[track_id]

        occupancy = len(self._retained)
        confidence = confidence_from_tracks(in_zone_tracks)
        transitions = self._occupancy_change(frame, occupancy, confidence)
        transitions.extend(self._crowd(frame, occupancy, confidence))
        return transitions

    def on_stream_end(
        self, *, monotonic: float, observed_at: datetime, reason: str
    ) -> list[EventTransition]:
        del monotonic
        if self._crowd_event is None:
            return []
        event = self._crowd_event
        self._crowd_event = None
        resolved = self._finalise_on_stream_end(event, observed_at=observed_at, reason=reason)
        return [resolved] if resolved is not None else []

    # -- helpers -----------------------------------------------------------------
    def _occupancy_change(
        self,
        frame: EngineFrame,
        occupancy: int,
        confidence: float | None,
    ) -> list[EventTransition]:
        if self._pending_count != occupancy:
            self._pending_count = occupancy
            self._pending_since = frame.monotonic
            return []
        if self._pending_since is None:
            return []
        if frame.monotonic - self._pending_since < self.thresholds.occupancy_persistence_seconds:
            return []
        if occupancy == self._last_reported:
            return []

        assert self._zone is not None
        previous = self._last_reported
        self._last_reported = occupancy
        active, opened = self._open(
            EventType.ROOM_OCCUPANCY_CHANGE,
            start_time=frame.observed_at,
            trigger_time=frame.observed_at,
            zone_id=self._zone.id,
            zone_name=self._zone.name,
            status=EventStatus.ACTIVE,
            certainty=certainty_from_confidence(confidence),
            confidence=confidence,
            attributes={
                "occupancy_count": occupancy,
                "previous_occupancy_count": previous,
            },
        )
        resolved = self._resolve(active, frame.observed_at, reason="occupancy_updated")
        return [opened, resolved]

    def _crowd(
        self,
        frame: EngineFrame,
        occupancy: int,
        confidence: float | None,
    ) -> list[EventTransition]:
        assert self._zone is not None
        threshold = self.thresholds.crowd_occupancy_threshold
        hysteresis = self.thresholds.crowd_release_hysteresis

        if occupancy >= threshold:
            self._crowd_low_since = None
            if self._crowd_event is None:
                if self._crowd_high_since is None:
                    self._crowd_high_since = frame.monotonic
                    self._crowd_high_since_at = frame.observed_at
                    return []
                if (
                    frame.monotonic - self._crowd_high_since
                    < self.thresholds.crowd_persistence_seconds
                ):
                    return []
                active, opened = self._open(
                    EventType.CROWD_FORMING,
                    start_time=self._crowd_high_since_at or frame.observed_at,
                    trigger_time=frame.observed_at,
                    zone_id=self._zone.id,
                    zone_name=self._zone.name,
                    status=EventStatus.ACTIVE,
                    certainty=certainty_from_confidence(confidence),
                    confidence=confidence,
                    attributes={
                        "occupancy_count": occupancy,
                        "threshold_people": threshold,
                        "persistence_seconds": self.thresholds.crowd_persistence_seconds,
                    },
                )
                self._crowd_event = active
                return [opened]
            if self._crowd_event.attributes.get("occupancy_count") != occupancy:
                return [
                    self._update(
                        self._crowd_event,
                        frame.observed_at,
                        attributes={"occupancy_count": occupancy},
                        certainty=certainty_from_confidence(confidence),
                        confidence=confidence,
                    )
                ]
            return []

        if occupancy <= threshold - hysteresis:
            self._crowd_high_since = None
            self._crowd_high_since_at = None
            if self._crowd_event is None:
                return []
            if self._crowd_low_since is None:
                self._crowd_low_since = frame.monotonic
                return []
            if frame.monotonic - self._crowd_low_since < self.thresholds.crowd_release_seconds:
                return []
            event = self._crowd_event
            self._crowd_event = None
            self._crowd_low_since = None
            return [self._resolve(event, frame.observed_at, reason="occupancy_below_threshold")]

        # Within the release hysteresis band: keep the current state.
        return []
