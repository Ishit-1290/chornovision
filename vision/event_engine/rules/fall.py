"""Potential-fall-from-bed rule (EV-07; G §8.7, W §7.7).

The rule needs two optional inputs that Phase 4 does not produce yet: a bed polygon and
pose observations (:class:`~vision.event_engine.types.PoseObservation`). Without pose
observations it stays inactive; it never infers posture from a person bounding box.

Evidence policy (G §8.7):

* A single low/floor frame is never enough. A credible event needs a recent
  "on the bed" observation followed, within ``fall_transition_window_seconds``, by a
  low/lying observation outside the bed region.
* A low posture in the configured floor region **without** an observed bed transition is
  opened as ``uncertain`` — the guideline explicitly says an unobserved transition must
  be labelled possible-fall/uncertain.
* The event is labelled as a potential fall only. It is never a medical conclusion
  (CON-10, NFR-07); severity is a presentation priority.
* The event completes when the person is observed upright for
  ``fall_confirmation_seconds``, and is left incomplete (``uncertain``) if the stream or
  track ends first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.events.types import (
    Certainty,
    EventStatus,
    EventTransition,
    EventType,
)
from app.events.zones import CameraRulesConfig, Point, Zone

from vision.event_engine.base import (
    ActiveEvent,
    BaseRule,
    EventIdFactory,
    certainty_from_confidence,
)
from vision.event_engine.geometry import (
    box_bottom_center,
    in_zone,
    normalise_box,
)
from vision.event_engine.types import EngineFrame, EntityObservation, PoseObservation, Posture


@dataclass
class _PersonState:
    last_seen: float
    on_bed_since: float | None = None
    on_bed_at: datetime | None = None
    upright_since: float | None = None
    event: ActiveEvent | None = None
    last_update: float | None = None


class FallRule(BaseRule):
    """Detect a bed-to-floor transition consistent with a possible fall."""

    event_types = (EventType.FALL_FROM_BED,)

    def __init__(
        self,
        *,
        camera_id: int,
        config: CameraRulesConfig,
        id_factory: EventIdFactory,
    ) -> None:
        super().__init__(camera_id=camera_id, config=config, id_factory=id_factory)
        self._bed: Zone | None = self.config.zone(self.config.bed_zone_id)
        self._floor: Zone | None = self.config.zone(self.config.floor_zone_id)
        self._states: dict[int, _PersonState] = {}

    def reset(self) -> None:
        self._states.clear()

    def observe(self, frame: EngineFrame) -> list[EventTransition]:
        if self._bed is None:
            return []

        transitions: list[EventTransition] = []
        seen: set[int] = set()
        for track in frame.person_tracks():
            seen.add(track.track_id)
            state = self._states.get(track.track_id)
            if state is None:
                state = _PersonState(last_seen=frame.monotonic)
                self._states[track.track_id] = state
            state.last_seen = frame.monotonic

            pose = frame.pose_for(track.track_id)
            if pose is None or pose.posture is Posture.UNKNOWN:
                # Insufficient visibility: do not advance or invent a transition.
                continue

            anchor = self._anchor(track, frame)
            in_bed = in_zone(anchor, self._bed)
            in_floor = in_zone(anchor, self._floor)

            if in_bed and pose.posture in (Posture.LYING, Posture.SITTING):
                state.on_bed_since = frame.monotonic
                state.on_bed_at = frame.observed_at
                state.upright_since = None
                if state.event is not None:
                    transitions.append(
                        self._resolve(
                            state.event,
                            frame.observed_at,
                            reason="person_returned_to_bed",
                        )
                    )
                    state.event = None
                continue

            if pose.posture is Posture.UPRIGHT:
                state.upright_since = (
                    frame.monotonic if state.upright_since is None else state.upright_since
                )
                if (
                    state.event is not None
                    and frame.monotonic - state.upright_since
                    >= self.thresholds.fall_confirmation_seconds
                ):
                    transitions.append(
                        self._resolve(state.event, frame.observed_at, reason="person_upright")
                    )
                    state.event = None
                continue

            # A lying (or very low) posture outside the bed.
            state.upright_since = None
            if not self._low_posture(pose):
                continue

            recent_bed_transition = (
                state.on_bed_since is not None
                and frame.monotonic - state.on_bed_since
                <= self.thresholds.fall_transition_window_seconds
            )
            confidence = pose.confidence

            if state.event is None:
                if not recent_bed_transition and not in_floor:
                    continue
                status = EventStatus.ACTIVE if recent_bed_transition else EventStatus.UNCERTAIN
                certainty = (
                    certainty_from_confidence(confidence)
                    if recent_bed_transition
                    else Certainty.UNKNOWN
                )
                active, opened = self._open(
                    EventType.FALL_FROM_BED,
                    start_time=state.on_bed_at or frame.observed_at,
                    trigger_time=frame.observed_at,
                    zone_id=self._bed.id,
                    zone_name=self._bed.name,
                    entity_id=track.track_id,
                    status=status,
                    certainty=certainty,
                    confidence=confidence,
                    attributes={
                        "bed_zone_name": self._bed.name,
                        "observed_bed_transition": recent_bed_transition,
                        "in_floor_zone": in_floor,
                        "posture": pose.posture.value,
                        "height_ratio": pose.height_ratio,
                    },
                )
                state.event = active
                state.last_update = frame.monotonic
                transitions.append(opened)
                continue

            interval = self.thresholds.fall_update_interval_seconds
            if state.last_update is None or frame.monotonic - state.last_update >= interval:
                state.last_update = frame.monotonic
                transitions.append(
                    self._update(
                        state.event,
                        frame.observed_at,
                        attributes={
                            "posture": pose.posture.value,
                            "height_ratio": pose.height_ratio,
                        },
                        confidence=confidence,
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

    def _low_posture(self, pose: PoseObservation) -> bool:
        if pose.posture is Posture.LYING:
            return True
        return (
            pose.height_ratio is not None
            and pose.height_ratio <= self.thresholds.fall_low_height_ratio
        )

    def _expire_absent(
        self, frame: EngineFrame, seen: set[int], transitions: list[EventTransition]
    ) -> None:
        tolerance = self.thresholds.fall_ambiguous_window_seconds
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
                    )
                )
            del self._states[track_id]

        self._trim_states(self._states)
