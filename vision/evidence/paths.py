"""Safe evidence path construction for the vision worker (Phase 6; FR-38, FR-41).

File names are **never** derived from untrusted event data. The storage layout is fixed by
the workflow (``evidence/camera-<id>/YYYY/MM/DD/...``); the only variable components are the
numeric camera id, the UTC capture date, and a sanitised form of the deterministic event id.
Every path is then resolved against ``EVIDENCE_DIR`` and rejected if it escapes it, so a
malicious or corrupted value can never read or write outside the evidence root.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings

#: Anything that is not a conservative filename character is collapsed to ``-``.
_UNSAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


class EvidencePathError(ValueError):
    """A constructed or supplied evidence path is unsafe."""


def evidence_root() -> Path:
    """Return the configured evidence directory (the single shared root)."""
    return Path(get_settings().evidence_dir).expanduser()


def sanitize_component(value: str, *, max_length: int = 64) -> str:
    """Collapse ``value`` to a safe path component (no separators, no traversal)."""
    cleaned = _UNSAFE_COMPONENT.sub("-", str(value)).strip("-._")
    return (cleaned or "evidence")[:max_length]


def build_relative_path(
    *,
    camera_id: int,
    captured_at: datetime,
    event_id: str,
    media_type: str,
    extension: str,
) -> str:
    """Build the canonical relative path for one evidence item."""
    if not isinstance(camera_id, int) or camera_id < 1:
        raise EvidencePathError("camera_id must be a positive integer")
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)
    moment = captured_at.astimezone(UTC)
    safe_event = sanitize_component(event_id)
    safe_type = sanitize_component(media_type, max_length=16)
    safe_ext = sanitize_component(extension, max_length=8).lower()
    if not safe_ext:
        raise EvidencePathError("extension must not be empty")
    filename = f"{safe_event}-{safe_type}.{safe_ext}"
    return f"camera-{camera_id}/{moment:%Y}/{moment:%m}/{moment:%d}/{filename}"


def is_safe_relative_path(relative_path: str) -> bool:
    """True when ``relative_path`` is relative and contains no traversal segments."""
    if not relative_path:
        return False
    normalised = relative_path.replace("\\", "/")
    if normalised.startswith("/"):
        return False
    if len(normalised) > 1 and normalised[1] == ":":  # Windows drive letter
        return False
    parts = [part for part in normalised.split("/") if part not in ("", ".")]
    if not parts:
        return False
    return all(part != ".." for part in parts)


def resolve_within_root(root: Path, relative_path: str) -> Path:
    """Resolve ``relative_path`` under ``root`` or raise :class:`EvidencePathError`."""
    base = root.expanduser().resolve()
    if not is_safe_relative_path(relative_path):
        raise EvidencePathError("unsafe evidence path")
    candidate = base.joinpath(*relative_path.replace("\\", "/").split("/")).resolve()
    if candidate != base and base not in candidate.parents:
        raise EvidencePathError("evidence path escapes the evidence directory")
    return candidate
