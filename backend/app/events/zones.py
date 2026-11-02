"""Camera-specific zones and configurable event-rule thresholds (Phase 5; NFR-09).

Zones are *predefined and camera-specific* (CON-03): a camera's ``configuration`` JSON
may contain a ``zones`` list plus an optional ``event_rules`` object. Coordinates are
normalised to ``[0, 1]`` against the processed frame size so a configuration is
resolution-independent.

All thresholds are explicit configuration. The defaults below are **proposals**, not
confirmed source requirements, except ``door_open_threshold_seconds`` (60 s),
``package_stationary_seconds`` (the source suggests 30–60 s) and
``motionless_duration_seconds`` (120 s), which come from ``../guidelines.md`` §8.
They are recorded in ``docs/DECISIONS.md`` (D-35).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


class ZoneKind(StrEnum):
    """What a predefined polygon represents."""

    ENTRANCE = "entrance"
    ROOM = "room"
    DOOR = "door"
    BED = "bed"
    FLOOR = "floor"
    PACKAGE_AREA = "package_area"
    OTHER = "other"


class BoundarySide(StrEnum):
    """Which side of the directed boundary line is the monitored interior."""

    LEFT = "left"
    RIGHT = "right"


class Point(BaseModel):
    """A normalised image coordinate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class BoundaryLine(BaseModel):
    """A directed entrance boundary.

    The line runs from ``p1`` to ``p2``. ``inside_side`` states which side of that
    directed line is the monitored interior; a track whose anchor crosses from the
    other side to this side is *entering*, and the reverse is *leaving*.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    p1: Point
    p2: Point
    inside_side: BoundarySide = BoundarySide.LEFT

    @model_validator(mode="after")
    def _check_distinct(self) -> BoundaryLine:
        if self.p1 == self.p2:
            raise ValueError("boundary p1 and p2 must differ")
        return self


class Zone(BaseModel):
    """A predefined camera zone."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=128)
    kind: ZoneKind
    polygon: list[Point] = Field(min_length=3)
    boundary: BoundaryLine | None = None


class EventThresholds(BaseModel):
    """All event-rule timings and tolerances (defaults are documented proposals)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # -- Entry / exit ---------------------------------------------------------
    boundary_confirm_frames: int = Field(default=2, ge=1, le=60)
    boundary_cooldown_seconds: float = Field(default=2.0, ge=0.0)
    boundary_side_epsilon: float = Field(default=0.005, ge=0.0, le=0.5)

    # -- Occupancy / crowd ----------------------------------------------------
    occupancy_persistence_seconds: float = Field(default=2.0, ge=0.0)
    occupancy_retention_seconds: float = Field(default=3.0, gt=0.0)
    crowd_occupancy_threshold: int = Field(default=3, ge=1)
    crowd_persistence_seconds: float = Field(default=15.0, ge=0.0)
    crowd_release_seconds: float = Field(default=5.0, ge=0.0)
    crowd_release_hysteresis: int = Field(default=1, ge=0)

    # -- Door -----------------------------------------------------------------
    door_open_threshold_seconds: float = Field(default=60.0, gt=0.0)
    door_unknown_tolerance_seconds: float = Field(default=5.0, ge=0.0)
    door_update_interval_seconds: float = Field(default=30.0, gt=0.0)

    # -- Package --------------------------------------------------------------
    package_stationary_seconds: float = Field(default=45.0, gt=0.0)
    package_stationary_tolerance: float = Field(default=0.02, ge=0.0, le=1.0)
    package_absence_tolerance_seconds: float = Field(default=5.0, ge=0.0)
    package_person_proximity: float = Field(default=0.15, ge=0.0, le=1.0)
    package_update_interval_seconds: float = Field(default=30.0, gt=0.0)

    # -- Motionlessness -------------------------------------------------------
    motionless_duration_seconds: float = Field(default=120.0, gt=0.0)
    motionless_movement_threshold: float = Field(default=0.01, ge=0.0, le=1.0)
    motionless_absence_tolerance_seconds: float = Field(default=3.0, ge=0.0)
    motionless_update_interval_seconds: float = Field(default=30.0, gt=0.0)
    motionless_min_observations: int = Field(default=5, ge=1)

    # -- Potential fall -------------------------------------------------------
    fall_transition_window_seconds: float = Field(default=5.0, gt=0.0)
    fall_ambiguous_window_seconds: float = Field(default=15.0, gt=0.0)
    fall_min_bed_seconds: float = Field(default=1.0, ge=0.0)
    fall_low_height_ratio: float = Field(default=0.18, ge=0.0, le=1.0)
    fall_confirmation_seconds: float = Field(default=5.0, ge=0.0)
    fall_update_interval_seconds: float = Field(default=5.0, gt=0.0)

    # -- Bounded per-camera rule state ---------------------------------------
    max_tracked_entities: int = Field(default=64, ge=1)


#: The zone kind each configured role must reference.
_ROLE_KINDS: dict[str, frozenset[ZoneKind]] = {
    "entrance_zone_id": frozenset({ZoneKind.ENTRANCE}),
    "room_zone_id": frozenset({ZoneKind.ROOM}),
    "door_zone_id": frozenset({ZoneKind.DOOR}),
    "package_zone_id": frozenset({ZoneKind.ENTRANCE, ZoneKind.PACKAGE_AREA}),
    "bed_zone_id": frozenset({ZoneKind.BED}),
    "floor_zone_id": frozenset({ZoneKind.FLOOR}),
}


class CameraRulesConfig(BaseModel):
    """Validated zones, role references, and thresholds for one camera."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config_version: str = Field(default="1", min_length=1, max_length=32)
    zones: list[Zone] = Field(default_factory=list)
    entrance_zone_id: str | None = None
    room_zone_id: str | None = None
    door_zone_id: str | None = None
    package_zone_id: str | None = None
    bed_zone_id: str | None = None
    floor_zone_id: str | None = None
    #: Detector class names treated as packages/parcels (lower-case, deduplicated).
    package_classes: tuple[str, ...] = (
        "package",
        "parcel",
        "box",
        "suitcase",
        "backpack",
        "handbag",
    )
    thresholds: EventThresholds = Field(default_factory=EventThresholds)

    @field_validator("package_classes")
    @classmethod
    def _normalise_package_classes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        seen: list[str] = []
        for item in value:
            name = item.strip().lower()
            if not name:
                raise ValueError("package class names must not be blank")
            if name not in seen:
                seen.append(name)
        if not seen:
            raise ValueError("package_classes must not be empty")
        return tuple(seen)

    @model_validator(mode="after")
    def _check_references(self) -> CameraRulesConfig:
        by_id: dict[str, Zone] = {}
        for zone in self.zones:
            if zone.id in by_id:
                raise ValueError(f"duplicate zone id {zone.id!r}")
            by_id[zone.id] = zone

        for role, allowed_kinds in _ROLE_KINDS.items():
            zone_id = getattr(self, role)
            if zone_id is None:
                continue
            zone = by_id.get(zone_id)
            if zone is None:
                raise ValueError(f"{role} references unknown zone {zone_id!r}")
            if zone.kind not in allowed_kinds:
                allowed = ", ".join(sorted(kind.value for kind in allowed_kinds))
                raise ValueError(f"{role} zone {zone_id!r} must have kind one of: {allowed}")
            if role == "entrance_zone_id" and zone.boundary is None:
                raise ValueError(f"entrance zone {zone_id!r} must define a boundary line")
        return self

    def zone(self, zone_id: str | None) -> Zone | None:
        """Return the zone with ``zone_id`` or ``None``."""
        if zone_id is None:
            return None
        for zone in self.zones:
            if zone.id == zone_id:
                return zone
        return None


class CameraRulesError(ValueError):
    """A camera's rule/zone configuration is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


#: Supported detection-time frame rotations, in degrees clockwise (D-72).
ALLOWED_ROTATIONS: tuple[int, ...] = (0, 90, 180, 270)


def parse_rotation(configuration: Mapping[str, Any] | None) -> int:
    """Return the validated detection rotation (degrees clockwise); default ``0``.

    ``rotation`` is an optional top-level key alongside ``zones`` and ``event_rules``. It
    tells the worker to rotate frames *for the detector* when a camera publishes a
    sideways picture; the stored zone geometry stays in the original camera frame, so a
    camera keeps working without redrawing zones. An unsupported value is rejected rather
    than silently ignored, so a typo never disables detection silently.
    """
    if not isinstance(configuration, Mapping):
        return 0
    value = configuration.get("rotation", 0)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value not in ALLOWED_ROTATIONS:
        allowed = ", ".join(str(item) for item in ALLOWED_ROTATIONS)
        raise CameraRulesError(f"rotation must be one of: {allowed}")
    return value


def _compact_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ()))
        message = str(error.get("msg", "invalid value"))
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts[:8])


def parse_camera_rules(configuration: Mapping[str, Any] | None) -> CameraRulesConfig:
    """Parse and validate a camera's ``configuration`` JSON.

    ``zones`` and ``event_rules`` are the only recognised keys. When neither is
    present the camera has no event rules and every rule stays inactive. Malformed
    input raises :class:`CameraRulesError` rather than being silently ignored.
    """
    if configuration is None:
        return CameraRulesConfig()
    if not isinstance(configuration, Mapping):
        raise CameraRulesError("camera configuration must be an object")

    raw_zones = configuration.get("zones", [])
    raw_rules = configuration.get("event_rules", {})
    if raw_rules is None:
        raw_rules = {}
    if not isinstance(raw_rules, Mapping):
        raise CameraRulesError("event_rules must be an object")

    data: dict[str, Any] = {"zones": raw_zones}
    for key, value in raw_rules.items():
        if key in data:
            raise CameraRulesError(f"event_rules must not redefine {key!r}")
        data[key] = value

    try:
        return CameraRulesConfig.model_validate(data)
    except ValidationError as exc:
        raise CameraRulesError(_compact_validation_error(exc)) from exc


def validate_camera_configuration(configuration: Mapping[str, Any] | None) -> None:
    """Validate a camera configuration; raise :class:`CameraRulesError` on failure."""
    parse_camera_rules(configuration)
    parse_rotation(configuration)
