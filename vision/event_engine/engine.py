"""Temporal event engine: one per camera (Phase 5; FR-16–FR-34).

The engine owns the configured rules for a single camera. It is deliberately free of any
decoder, detector, database, network, or HTTP dependency: the worker adapts a processed
frame into an :class:`~vision.event_engine.types.EngineFrame`, and the engine returns and
publishes deterministic :class:`~app.events.types.EventTransition` objects through an
:class:`~vision.event_engine.types.EventSink`.

Rules are isolated from one another: a rule that raises is logged and skipped for that
frame, so one activity can never stop the others or the camera worker. This is the
"detect independently, hand off separately" boundary that keeps persistence (Phase 6)
off the frame-processing path.

``reset()`` must be called on every new connection (the worker does this alongside the
tracker reset, FR-08): no event is inferred across a stream gap, and a person visible at
the start of a new stream is never treated as entering.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.events.types import EventTransition, EventType
from app.events.zones import CameraRulesConfig, parse_camera_rules

from vision.event_engine.base import BaseRule, EventIdFactory
from vision.event_engine.rules import (
    BoundaryCrossingRule,
    DoorOpenRule,
    FallRule,
    MotionlessRule,
    OccupancyRule,
    PackageRule,
)
from vision.event_engine.types import EngineFrame, EventSink, NullEventSink

LOGGER = logging.getLogger("vision.event_engine")


class TemporalEventEngine:
    """Per-camera rule orchestration and deterministic transition publishing."""

    def __init__(
        self,
        *,
        camera_id: int,
        config: CameraRulesConfig,
        rules: list[BaseRule],
        event_sink: EventSink | None = None,
        id_factory: EventIdFactory | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.config = config
        self._rules = list(rules)
        self._sink: EventSink = event_sink or NullEventSink()
        self._ids = id_factory
        self._logger = logger or LOGGER
        self._error_count = 0

    # -- construction ------------------------------------------------------------
    @classmethod
    def from_camera(
        cls,
        camera_id: int,
        configuration: dict[str, Any] | None,
        *,
        event_sink: EventSink | None = None,
        logger: logging.Logger | None = None,
    ) -> TemporalEventEngine:
        """Build an engine from a camera's ``configuration`` JSON.

        Only configured activity inputs create a rule. Motionlessness needs no zone and
        is always enabled; door, package and fall rules are created only when their
        zone is configured, and remain inactive until the corresponding optional input
        (door state, package detections, pose) is actually produced.
        """
        config = parse_camera_rules(configuration)
        ids = EventIdFactory(camera_id)
        rules: list[BaseRule] = []
        if config.entrance_zone_id is not None:
            rules.append(BoundaryCrossingRule(camera_id=camera_id, config=config, id_factory=ids))
        if config.room_zone_id is not None:
            rules.append(OccupancyRule(camera_id=camera_id, config=config, id_factory=ids))
        if config.door_zone_id is not None:
            rules.append(DoorOpenRule(camera_id=camera_id, config=config, id_factory=ids))
        if config.package_zone_id is not None:
            rules.append(PackageRule(camera_id=camera_id, config=config, id_factory=ids))
        rules.append(MotionlessRule(camera_id=camera_id, config=config, id_factory=ids))
        if config.bed_zone_id is not None:
            rules.append(FallRule(camera_id=camera_id, config=config, id_factory=ids))
        return cls(
            camera_id=camera_id,
            config=config,
            rules=rules,
            event_sink=event_sink,
            id_factory=ids,
            logger=logger,
        )

    # -- public API --------------------------------------------------------------
    @property
    def event_types(self) -> tuple[EventType, ...]:
        """Every event type this camera's configured rules can emit."""
        return tuple(event_type for rule in self._rules for event_type in rule.event_types)

    @property
    def error_count(self) -> int:
        return self._error_count

    def observe(self, frame: EngineFrame) -> list[EventTransition]:
        """Advance every rule by one processed frame and publish transitions."""
        if frame.camera_id != self.camera_id:
            raise ValueError(
                f"frame camera_id {frame.camera_id} does not match engine {self.camera_id}"
            )
        return self._run(lambda rule: rule.observe(frame))

    def on_stream_end(
        self, *, monotonic: float, observed_at: datetime, reason: str = "stream_ended"
    ) -> list[EventTransition]:
        """Finalise open persistent events when the stream/session ends."""
        return self._run(
            lambda rule: rule.on_stream_end(
                monotonic=monotonic, observed_at=observed_at, reason=reason
            )
        )

    def reset(self) -> None:
        """Clear all temporal state for a new connection/session (FR-08)."""
        if self._ids is not None:
            self._ids.reset()
        for rule in self._rules:
            try:
                rule.reset()
            except Exception:  # pragma: no cover - defensive
                self._error_count += 1
                self._logger.exception(
                    "camera %s: failed to reset rule %s",
                    self.camera_id,
                    type(rule).__name__,
                )

    # -- internals ---------------------------------------------------------------
    def _run(self, produce: Callable[[BaseRule], list[EventTransition]]) -> list[EventTransition]:
        transitions: list[EventTransition] = []
        for rule in self._rules:
            try:
                produced = produce(rule)
            except Exception:
                self._error_count += 1
                self._logger.exception(
                    "camera %s: rule %s failed",
                    self.camera_id,
                    type(rule).__name__,
                )
                continue
            for transition in produced:
                self._publish(transition)
                transitions.append(transition)
        return transitions

    def _publish(self, transition: EventTransition) -> None:
        try:
            self._sink.publish(transition)
        except Exception:
            # A failing handoff must never break frame processing or other rules.
            self._error_count += 1
            self._logger.warning(
                "camera %s: event sink rejected %s",
                self.camera_id,
                transition.event.event_id,
            )


def build_engine(
    camera_id: int,
    configuration: dict[str, Any] | None,
    *,
    event_sink: EventSink | None = None,
    logger: logging.Logger | None = None,
) -> TemporalEventEngine:
    """Convenience constructor used by the camera worker."""
    return TemporalEventEngine.from_camera(
        camera_id, configuration, event_sink=event_sink, logger=logger
    )
