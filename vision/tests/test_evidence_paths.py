"""Evidence path safety tests (Phase 6; FR-38, SEC-08)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from vision.evidence.paths import (
    EvidencePathError,
    build_relative_path,
    is_safe_relative_path,
    resolve_within_root,
    sanitize_component,
)

CAPTURED = datetime(2026, 3, 7, 4, 5, 6, tzinfo=UTC)


def test_build_relative_path_uses_fixed_camera_and_date_layout() -> None:
    relative = build_relative_path(
        camera_id=7,
        captured_at=CAPTURED,
        event_id="abc-123",
        media_type="clip",
        extension="MP4",
    )

    assert relative == "camera-7/2026/03/07/abc-123-clip.mp4"


def test_build_relative_path_never_trusts_event_id() -> None:
    relative = build_relative_path(
        camera_id=1,
        captured_at=CAPTURED,
        event_id="../../etc/passwd",
        media_type="snapshot",
        extension="jpg",
    )

    assert relative.startswith("camera-1/2026/03/07/")
    assert ".." not in relative
    assert not relative.startswith("/")
    assert "/etc/" not in relative
    assert is_safe_relative_path(relative)


def test_naive_capture_time_is_treated_as_utc() -> None:
    relative = build_relative_path(
        camera_id=1,
        captured_at=datetime(2026, 3, 7, 4, 5, 6),
        event_id="e",
        media_type="snapshot",
        extension="jpg",
    )
    assert relative == "camera-1/2026/03/07/e-snapshot.jpg"


@pytest.mark.parametrize("camera_id", [0, -1])
def test_build_relative_path_rejects_invalid_camera_id(camera_id: int) -> None:
    with pytest.raises(EvidencePathError):
        build_relative_path(
            camera_id=camera_id,
            captured_at=CAPTURED,
            event_id="e",
            media_type="snapshot",
            extension="jpg",
        )


def test_sanitize_component_collapses_unsafe_characters() -> None:
    assert sanitize_component("../a b/c\\d") == "a-b-c-d"
    assert sanitize_component("") == "evidence"
    assert sanitize_component("...---") == "evidence"


@pytest.mark.parametrize(
    "value",
    ["", "/etc/passwd", "../x", "a/../../b", "C:\\x", "a\\..\\b", ".", ".."],
)
def test_unsafe_relative_paths_are_rejected(value: str) -> None:
    assert is_safe_relative_path(value) is False


@pytest.mark.parametrize("value", ["camera-1/2026/01/01/a.jpg", "a/b", "./a/b", "a//b"])
def test_safe_relative_paths_are_accepted(value: str) -> None:
    assert is_safe_relative_path(value) is True


def test_resolve_within_root_confines_to_root(tmp_path: Path) -> None:
    resolved = resolve_within_root(tmp_path, "camera-1/a.jpg")
    assert resolved == (tmp_path / "camera-1" / "a.jpg").resolve()


def test_resolve_within_root_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(EvidencePathError):
        resolve_within_root(tmp_path, "../outside.jpg")


def test_resolve_within_root_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-evidence"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:  # pragma: no cover - platform denial
        pytest.skip("symlinks are unavailable")
    with pytest.raises(EvidencePathError):
        resolve_within_root(tmp_path, "link/escape.jpg")
