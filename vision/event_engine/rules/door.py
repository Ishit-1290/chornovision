"""Door-open-too-long rule (EV-04; G §8.4, W §7.4).

The rule needs an **observed door state**, which no Phase 4 detector produces yet. It is
therefore wired to a dedicated input (:class:`~vision.event_engine.types.DoorStateObservation`)
and stays inactive until such observations are supplied — it never invents a door state
from person tracks.

Semantics follow G §8.4 exactly:

* the estimated open time is recorded when the door is first seen open;
* an event is generated once the open duration exceeds ``door_open_threshold_seconds``;
* the event is updated (throttled) while the door stays open;
* the event completes when the door is observed closing;
* if the stream ends while the door is still open the event is left incomplete
  (``uncertain``) rather than silently completed.

Brief classifier uncertainty is tolerated for ``door_unknown_tolerance_seconds`` by
holding the last known state, which is what prevents duplicate events on flicker.
"""

from __future__ import annotations

from datetime import datetime

from app.events.types import (
    EventAction,
    EventStatus,
    EventTransition,
    EventType,
)
from app.events.zones import CameraRulesConfig, Zone

from vision.event_engine.base import (
    ActiveEvent,
    BaseRule,
    EventIdFactory,
    certainty_from_confidence,
)
from vision.event_engine.types import DoorState, DoorStateObservation, EngineFrame


class DoorOpenRule(BaseRule):
    """Track sustained door-open duration."""

    event_types = (EventType.DOOR_OPEN_TOO_LONG,)

    def __init__(
        self,
        *,
        camera_id: int,
        config: CameraRulesConfig,
        id_factory: EventIdFactory,
    ) -> None:
        super().__init__(camera_id=camera_id, config=config, id_factory=id_factory)
        self._zone: Zone | None = self.config.zone(self.config.door_zone_id)
        self._last_known: DoorState | None = None
        self._unknown_since: float | None = None
        self._open_since: float | None = None
        self._open_since_at: datetime | None = None
        self._event: ActiveEvent | None = None
        self._last_update: float | None = None

    def reset(self) -> None:
        self._last_known = None
        self._unknown_since = None
        self._open_since = None
        self._open_since_at = None
        self._event = None
        self._last_update = None

    def observe(self, frame: EngineFrame) -> list[EventTransition]:
        if self._zone is None:
            return []
        observation = frame.door_state(self._zone.id)
        state = self._resolved_state(observation, frame.monotonic)

        if state is DoorState.OPEN:
            return self._on_open(frame, observation.confidence if observation else None)
        if state is DoorState.CLOSED:
            return self._on_closed(frame)
        return self._on_unknown(frame)

    def on_stream_end(
        self, *, monotonic: float, observed_at: datetime, reason: str
    ) -> list[EventTransition]:
        del monotonic
        if self._event is None:
            return []
        event = self._event
        self._event = None
        transition = self._finalise_on_stream_end(event, observed_at=observed_at, reason=reason)
        return [transition] if transition is not None else []

    # -- helpers -----------------------------------------------------------------
    def _resolved_state(
        self, observation: DoorStateObservation | None, monotonic: float
    ) -> DoorState:
        if observation is not None and observation.state is not DoorState.UNKNOWN:
            self._last_known = observation.state
            self._unknown_since = None
            return observation.state
        if self._last_known is None:
            return DoorState.UNKNOWN
        if self._unknown_since is None:
            self._unknown_since = monotonic
        if monotonic - self._unknown_since <= self.thresholds.door_unknown_tolerance_seconds:
            return self._last_known
        return DoorState.UNKNOWN

    def _on_open(self, frame: EngineFrame, confidence: float | None) -> list[EventTransition]:
        assert self._zone is not None
        if self._open_since is None:
            self._open_since = frame.monotonic
            self._open_since_at = frame.observed_at
        duration = frame.monotonic - self._open_since
        threshold = self.thresholds.door_open_threshold_seconds

        if self._event is None:
            if duration < threshold:
                return []
            active, opened = self._open(
                EventType.DOOR_OPEN_TOO_LONG,
                start_time=self._open_since_at or frame.observed_at,
                trigger_time=frame.observed_at,
                zone_id=self._zone.id,
                zone_name=self._zone.name,
                status=EventStatus.ACTIVE,
                certainty=certainty_from_confidence(confidence),
                confidence=confidence,
                attributes={
                    "duration_seconds": round(duration, 3),
                    "threshold_seconds": threshold,
                },
            )
            self._event = active
            self._last_update = frame.monotonic
            return [opened]

        attributes = {"duration_seconds": round(duration, 3)}
        if self._event.status is EventStatus.UNCERTAIN:
            self._last_update = frame.monotonic
            return [
                self._emit(
                    self._event,
                    action=EventAction.UPDATED,
                    status=EventStatus.ACTIVE,
                    at=frame.observed_at,
                    attributes=attributes,
                )
            ]
        interval = self.thresholds.door_update_interval_seconds
        if self._last_update is None or frame.monotonic - self._last_update >= interval:
            self._last_update = frame.monotonic
            return [self._update(self._event, frame.observed_at, attributes=attributes)]
        return []

    def _on_closed(self, frame: EngineFrame) -> list[EventTransition]:
        self._open_since = None
        self._open_since_at = None
        self._unknown_since = None
        if self._event is None:
            return []
        event = self._event
        self._event = None
        return [self._resolve(event, frame.observed_at, reason="door_closed")]

    def _on_unknown(self, frame: EngineFrame) -> list[EventTransition]:
        if self._event is None or self._event.status is EventStatus.UNCERTAIN:
            return []
        return [self._mark_uncertain(self._event, frame.observed_at, reason="door_state_unknown")]
