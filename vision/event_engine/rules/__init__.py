"""Temporal activity rules (Phase 5).

Each module implements one activity (or one related pair, as with entry/exit) as a
:class:`~vision.event_engine.base.BaseRule`. Rules never touch the decoder, detector,
database, network, or an HTTP handler: they consume an
:class:`~vision.event_engine.types.EngineFrame` and emit deterministic
:class:`~app.events.types.EventTransition` objects.
"""

from __future__ import annotations

from vision.event_engine.rules.boundary import BoundaryCrossingRule
from vision.event_engine.rules.door import DoorOpenRule
from vision.event_engine.rules.fall import FallRule
from vision.event_engine.rules.motionless import MotionlessRule
from vision.event_engine.rules.occupancy import OccupancyRule
from vision.event_engine.rules.package import PackageRule

__all__ = [
    "BoundaryCrossingRule",
    "DoorOpenRule",
    "FallRule",
    "MotionlessRule",
    "OccupancyRule",
    "PackageRule",
]
