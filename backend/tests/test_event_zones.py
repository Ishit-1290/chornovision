"""Tests for camera zones and event-rule configuration (Phase 5; NFR-09)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.events.zones import (
    ALLOWED_ROTATIONS,
    CameraRulesConfig,
    CameraRulesError,
    EventThresholds,
    ZoneKind,
    parse_camera_rules,
    parse_rotation,
    validate_camera_configuration,
)


def _zone(zone_id: str = "entrance", **overrides: object) -> dict[str, object]:
    zone: dict[str, object] = {
        "id": zone_id,
        "name": "Front entrance",
        "kind": "entrance",
        "polygon": [
            {"x": 0.0, "y": 0.0},
            {"x": 1.0, "y": 0.0},
            {"x": 1.0, "y": 1.0},
        ],
        "boundary": {
            "p1": {"x": 0.0, "y": 0.5},
            "p2": {"x": 1.0, "y": 0.5},
            "inside_side": "left",
        },
    }
    zone.update(overrides)
    return zone


def _config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "zones": [_zone()],
        "event_rules": {"entrance_zone_id": "entrance"},
    }
    config.update(overrides)
    return config


# --- parsing basics ------------------------------------------------------------


def test_missing_configuration_means_no_rules() -> None:
    parsed = parse_camera_rules(None)
    assert parsed.zones == []
    assert parsed.entrance_zone_id is None
    assert parsed.thresholds == EventThresholds()


def test_empty_configuration_means_no_rules() -> None:
    assert parse_camera_rules({}).zones == []


def test_valid_entrance_configuration_parses() -> None:
    parsed = parse_camera_rules(_config())
    assert parsed.entrance_zone_id == "entrance"
    zone = parsed.zone("entrance")
    assert zone is not None
    assert zone.kind is ZoneKind.ENTRANCE
    assert zone.boundary is not None
    assert len(zone.polygon) == 3


def test_event_rules_object_is_merged_with_zones() -> None:
    parsed = parse_camera_rules(
        {
            "zones": [_zone()],
            "event_rules": {
                "entrance_zone_id": "entrance",
                "thresholds": {"door_open_threshold_seconds": 90},
            },
        }
    )
    assert parsed.entrance_zone_id == "entrance"
    assert parsed.thresholds.door_open_threshold_seconds == 90.0


def test_zone_lookup_returns_none_for_unknown_or_missing() -> None:
    parsed = parse_camera_rules(_config())
    assert parsed.zone("nope") is None
    assert parsed.zone(None) is None


# --- shape validation ----------------------------------------------------------


@pytest.mark.parametrize("configuration", [[], "zones", 3])
def test_configuration_must_be_an_object(configuration: object) -> None:
    with pytest.raises(CameraRulesError, match="must be an object"):
        parse_camera_rules(configuration)  # type: ignore[arg-type]


def test_event_rules_must_be_an_object() -> None:
    with pytest.raises(CameraRulesError, match="event_rules must be an object"):
        parse_camera_rules({"event_rules": []})


def test_event_rules_must_not_redefine_zones() -> None:
    with pytest.raises(CameraRulesError, match="must not redefine"):
        parse_camera_rules({"zones": [], "event_rules": {"zones": []}})


def test_unknown_top_level_configuration_keys_are_ignored() -> None:
    # ``configuration`` may hold unrelated camera settings; only zones/event_rules
    # are interpreted by the event engine.
    assert parse_camera_rules({"other": 1}).zones == []


def test_zone_polygon_requires_three_points() -> None:
    with pytest.raises(CameraRulesError):
        parse_camera_rules(
            {
                "zones": [
                    _zone(
                        polygon=[
                            {"x": 0.0, "y": 0.0},
                            {"x": 1.0, "y": 1.0},
                        ]
                    )
                ]
            }
        )


@pytest.mark.parametrize("coordinate", [-0.1, 1.1])
def test_zone_points_must_be_normalised(coordinate: float) -> None:
    with pytest.raises(CameraRulesError):
        parse_camera_rules({"zones": [_zone(polygon=[{"x": coordinate, "y": 0.0}] * 3)]})


def test_boundary_points_must_differ() -> None:
    boundary = {
        "p1": {"x": 0.5, "y": 0.5},
        "p2": {"x": 0.5, "y": 0.5},
    }
    with pytest.raises(CameraRulesError, match="must differ"):
        parse_camera_rules(
            {
                "zones": [
                    {
                        "id": "door",
                        "name": "Door",
                        "kind": "door",
                        "polygon": [
                            {"x": 0.0, "y": 0.0},
                            {"x": 1.0, "y": 0.0},
                            {"x": 1.0, "y": 1.0},
                        ],
                        "boundary": boundary,
                    }
                ]
            }
        )


@pytest.mark.parametrize("zone_id", ["Upper", "-leading", "with space", ""])
def test_zone_ids_must_match_the_stable_pattern(zone_id: str) -> None:
    with pytest.raises(CameraRulesError):
        parse_camera_rules({"zones": [_zone(zone_id)]})


def test_duplicate_zone_ids_are_rejected() -> None:
    with pytest.raises(CameraRulesError, match="duplicate zone id"):
        parse_camera_rules({"zones": [_zone("a"), _zone("a")]})


# --- role references -----------------------------------------------------------


def test_role_reference_must_exist() -> None:
    with pytest.raises(CameraRulesError, match="references unknown zone"):
        parse_camera_rules({"zones": [], "event_rules": {"room_zone_id": "room"}})


def test_role_reference_must_use_the_matching_kind() -> None:
    with pytest.raises(CameraRulesError, match="must have kind one of"):
        parse_camera_rules(
            {
                "zones": [
                    {
                        "id": "room",
                        "name": "Room",
                        "kind": "entrance",
                        "polygon": [
                            {"x": 0.0, "y": 0.0},
                            {"x": 1.0, "y": 0.0},
                            {"x": 1.0, "y": 1.0},
                        ],
                    }
                ],
                "event_rules": {"room_zone_id": "room"},
            }
        )


def test_entrance_zone_requires_a_boundary_line() -> None:
    zone = _zone()
    zone.pop("boundary")
    with pytest.raises(CameraRulesError, match="must define a boundary line"):
        parse_camera_rules({"zones": [zone], "event_rules": {"entrance_zone_id": "entrance"}})


def test_package_zone_accepts_entrance_or_package_area() -> None:
    for kind in ("entrance", "package_area"):
        zone = _zone("parcel", kind=kind)
        if kind == "package_area":
            zone.pop("boundary")
        parsed = parse_camera_rules({"zones": [zone], "event_rules": {"package_zone_id": "parcel"}})
        assert parsed.zone("parcel") is not None


def test_floor_zone_role_is_valid() -> None:
    zone = {
        "id": "floor",
        "name": "Floor area",
        "kind": "floor",
        "polygon": [
            {"x": 0.0, "y": 0.0},
            {"x": 1.0, "y": 0.0},
            {"x": 1.0, "y": 1.0},
        ],
    }
    parsed = parse_camera_rules({"zones": [zone], "event_rules": {"floor_zone_id": "floor"}})
    assert parsed.floor_zone_id == "floor"


# --- thresholds ----------------------------------------------------------------


def test_threshold_defaults_are_documented_values() -> None:
    thresholds = EventThresholds()
    assert thresholds.door_open_threshold_seconds == 60.0
    assert thresholds.package_stationary_seconds == 45.0
    assert thresholds.motionless_duration_seconds == 120.0
    assert thresholds.crowd_occupancy_threshold == 3
    assert thresholds.boundary_confirm_frames == 2


def test_thresholds_can_be_overridden() -> None:
    thresholds = EventThresholds.model_validate(
        {
            "crowd_occupancy_threshold": 5,
            "motionless_duration_seconds": 90,
            "boundary_confirm_frames": 1,
        }
    )
    assert thresholds.crowd_occupancy_threshold == 5
    assert thresholds.motionless_duration_seconds == 90
    assert thresholds.boundary_confirm_frames == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("door_open_threshold_seconds", 0),
        ("motionless_duration_seconds", 0),
        ("crowd_occupancy_threshold", 0),
        ("boundary_confirm_frames", 0),
        ("max_tracked_entities", 0),
        ("boundary_side_epsilon", 0.75),
        ("package_stationary_tolerance", 1.5),
    ],
)
def test_thresholds_enforce_bounds(field: str, value: float) -> None:
    with pytest.raises(CameraRulesError):
        parse_camera_rules({"event_rules": {"thresholds": {field: value}}})


def test_thresholds_reject_unknown_fields() -> None:
    with pytest.raises(CameraRulesError):
        parse_camera_rules({"event_rules": {"thresholds": {"made_up": 1}}})


# --- package classes -----------------------------------------------------------


def test_package_classes_are_lowercased_and_deduplicated() -> None:
    parsed = parse_camera_rules({"event_rules": {"package_classes": ["Box", " box ", "Parcel"]}})
    assert parsed.package_classes == ("box", "parcel")


def test_package_classes_cannot_be_blank_or_empty() -> None:
    with pytest.raises(CameraRulesError, match="must not be blank"):
        parse_camera_rules({"event_rules": {"package_classes": ["box", "  "]}})
    with pytest.raises(CameraRulesError, match="must not be empty"):
        parse_camera_rules({"event_rules": {"package_classes": []}})


# --- public validation helper --------------------------------------------------


def test_validate_camera_configuration_accepts_a_valid_config() -> None:
    assert validate_camera_configuration(_config()) is None


def test_validate_camera_configuration_raises_camera_rules_error() -> None:
    with pytest.raises(CameraRulesError):
        validate_camera_configuration(
            {"event_rules": {"thresholds": {"crowd_occupancy_threshold": 0}}}
        )


def test_config_is_frozen() -> None:
    parsed = parse_camera_rules(_config())
    with pytest.raises(ValidationError):
        parsed.thresholds.crowd_occupancy_threshold = 9  # type: ignore[misc]


def test_camera_rules_config_can_be_built_directly() -> None:
    parsed = CameraRulesConfig.model_validate({"zones": [_zone()], "entrance_zone_id": "entrance"})
    assert parsed.entrance_zone_id == "entrance"


# --- detection rotation (D-72) -------------------------------------------------


def test_missing_rotation_defaults_to_zero() -> None:
    assert parse_rotation(None) == 0
    assert parse_rotation({}) == 0
    assert parse_rotation({"rotation": None}) == 0


@pytest.mark.parametrize("rotation", ALLOWED_ROTATIONS)
def test_supported_rotations_are_accepted(rotation: int) -> None:
    assert parse_rotation({"rotation": rotation}) == rotation


def test_invalid_rotation_is_rejected_loudly() -> None:
    # A typo must not silently disable detection.
    with pytest.raises(CameraRulesError, match="rotation must be one of") as excinfo:
        parse_rotation({"rotation": 45})
    assert "0, 90, 180, 270" in str(excinfo.value)


@pytest.mark.parametrize("value", ["90", 90.0, True, [90]])
def test_non_integer_or_boolean_rotation_is_rejected(value: object) -> None:
    with pytest.raises(CameraRulesError):
        parse_rotation({"rotation": value})


def test_validate_camera_configuration_checks_the_rotation() -> None:
    assert validate_camera_configuration({**_config(), "rotation": 90}) is None
    with pytest.raises(CameraRulesError):
        validate_camera_configuration({**_config(), "rotation": 450})
