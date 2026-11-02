"""Person-motionless rule (EV-06; G §8.6, W §7.6).

Motion is measured as the per-frame displacement of a track's bottom-centre anchor. When
displacement stays at or below ``motionless_movement_threshold`` for
``motionless_duration_seconds`` and at least ``motionless_min_observations`` frames were
seen, one persistent ``person_motionless`` event is opened. It is updated while the
condition holds and completed when meaningful movement resumes (G §8.6).

The wording and structured certainty deliberately avoid equating motionlessness with
unconsciousness or a medical emergency (CON-10, NFR-07): the event is a review prompt,
and quiet sitting/sleeping are documented confounders. If the track disappears the event
is marked ``uncertain`` rather than completed, because absence is not evidence of
movement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.events.types import EventStatus, EventTransition, EventType
from app.events.zones import CameraRulesConfig, Point

from vision.event_engine.base import (
    ActiveEvent,
    BaseRule,
    EventIdFactory,
    certainty_from_confidence,
)
from vision.event_engine.geometry import (
    box_bottom_center,
    distance,
    normalise_box,
)
from vision.event_engine.types import EngineFrame, EntityObservation


@dataclass
class _PersonState:
    last_anchor: Point
    last_seen: float
    still_since: float
    still_since_at: datetime
    observations: int
    event: ActiveEvent | None = None
    last_update: float | None = None


class MotionlessRule(BaseRule):
    """Track sustained person inactivity."""

    event_types = (EventType.PERSON_MOTIONLESS,)

    def __init__(
        self,
        *,
        camera_id: int,
        config: CameraRulesConfig,
        id_factory: EventIdFactory,
    ) -> None:
        super().__init__(camera_id=camera_id, config=config, id_factory=id_factory)
        self._states: dict[int, _PersonState] = {}

    def reset(self) -> None:
        self._states.clear()

    def observe(self, frame: EngineFrame) -> list[EventTransition]:
        transitions: list[EventTransition] = []
        seen: set[int] = set()

        for track in frame.person_tracks():
            anchor = self._anchor(track, frame)
            seen.add(track.track_id)
            state = self._states.get(track.track_id)
            if state is None:
                self._states[track.track_id] = _PersonState(
                    last_anchor=anchor,
                    last_seen=frame.monotonic,
                    still_since=frame.monotonic,
                    still_since_at=frame.observed_at,
                    observations=1,
                )
                continue

            movement = distance(anchor, state.last_anchor)
            state.last_anchor = anchor
            state.last_seen = frame.monotonic
            state.observations += 1

            if movement > self.thresholds.motionless_movement_threshold:
                if state.event is not None:
                    transitions.append(
                        self._resolve(
                            state.event,
                            frame.observed_at,
                            reason="movement_resumed",
                        )
                    )
                    state.event = None
                state.still_since = frame.monotonic
                state.still_since_at = frame.observed_at
                state.observations = 1
                continue

            duration = frame.monotonic - state.still_since
            if state.event is None:
                if (
                    duration < self.thresholds.motionless_duration_seconds
                    or state.observations < self.thresholds.motionless_min_observations
                ):
                    continue
                confidence = track.confidence if 0.0 < track.confidence <= 1.0 else None
                active, opened = self._open(
                    EventType.PERSON_MOTIONLESS,
                    start_time=state.still_since_at,
                    trigger_time=frame.observed_at,
                    zone_id=None,
                    zone_name=None,
                    entity_id=track.track_id,
                    status=EventStatus.ACTIVE,
                    certainty=certainty_from_confidence(confidence),
                    confidence=confidence,
                    attributes={
                        "duration_seconds": round(duration, 3),
                        "movement_threshold": (self.thresholds.motionless_movement_threshold),
                        "observations": state.observations,
                    },
                )
                state.event = active
                state.last_update = frame.monotonic
                transitions.append(opened)
                continue

            interval = self.thresholds.motionless_update_interval_seconds
            if state.last_update is None or frame.monotonic - state.last_update >= interval:
                state.last_update = frame.monotonic
                transitions.append(
                    self._update(
                        state.event,
                        frame.observed_at,
                        attributes={"duration_seconds": round(duration, 3)},
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
        tolerance = self.thresholds.motionless_absence_tolerance_seconds
        for track_id in list(self._states):
            state = self._states[track_id]
            if track_id in seen:
                continue
            if frame.monotonic - state.last_seen <= tolerance:
                continue
            if state.event is not None:
                transitions.append(
                    self._mark_uncertain(
                        state.event,
                        frame.observed_at,
                        reason="track_not_observed",
                        end_time=frame.observed_at,
                        attributes={
                            "duration_seconds": round(frame.monotonic - state.still_since, 3)
                        },
                    )
                )
            del self._states[track_id]

        limit = self.thresholds.max_tracked_entities
        if len(self._states) > limit:
            ordered = sorted(self._states.items(), key=lambda item: item[1].last_seen)
            for track_id, _state in ordered[: len(self._states) - limit]:
                del self._states[track_id]
