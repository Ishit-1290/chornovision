"""Filesystem evidence store for the vision worker (Phase 6; FR-36, FR-41).

The store owns the write side of evidence. It builds a safe relative path (see
:mod:`vision.evidence.paths`), writes the bytes under ``EVIDENCE_DIR``, and returns an
:class:`EvidenceRecord` that the handoff submits to the backend. A failure is reported as an
explicit ``failed`` record instead of a silent gap, so the event stays visible with an
unambiguous evidence status (FR-39).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from vision.evidence.encoding import EvidenceEncoder, OpenCVEncoder
from vision.evidence.paths import EvidencePathError, build_relative_path, evidence_root

LOGGER = logging.getLogger("vision.evidence.store")


@dataclass(frozen=True)
class EvidenceRecord:
    """One evidence item ready to be registered with the backend."""

    event_id: str
    media_type: str
    status: str
    relative_path: str | None
    file_size_bytes: int | None
    duration_seconds: float | None
    captured_at: datetime
    error: str | None = None


class EvidenceStore:
    """Writes evidence bytes and describes the result."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        encoder: EvidenceEncoder | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._root = root
        self._encoder = encoder or OpenCVEncoder()
        self._logger = logger or LOGGER

    @property
    def root(self) -> Path:
        return Path(self._root) if self._root is not None else evidence_root()

    def save_snapshot(
        self, *, camera_id: int, event_id: str, captured_at: datetime, image: Any
    ) -> EvidenceRecord:
        relative = build_relative_path(
            camera_id=camera_id,
            captured_at=captured_at,
            event_id=event_id,
            media_type="snapshot",
            extension="jpg",
        )
        return self._write(
            relative=relative,
            event_id=event_id,
            media_type="snapshot",
            captured_at=captured_at,
            writer=lambda path: self._encoder.write_snapshot(path, image),
            duration_seconds=None,
        )

    def save_clip(
        self,
        *,
        camera_id: int,
        event_id: str,
        captured_at: datetime,
        frames: Sequence[Any],
        fps: float,
    ) -> EvidenceRecord:
        relative = build_relative_path(
            camera_id=camera_id,
            captured_at=captured_at,
            event_id=event_id,
            media_type="clip",
            extension="mp4",
        )
        duration = (len(frames) / fps) if fps > 0 and frames else None
        return self._write(
            relative=relative,
            event_id=event_id,
            media_type="clip",
            captured_at=captured_at,
            writer=lambda path: self._encoder.write_clip(path, frames, fps),
            duration_seconds=duration,
            require_frames=True,
            frames=frames,
        )

    def _write(
        self,
        *,
        relative: str,
        event_id: str,
        media_type: str,
        captured_at: datetime,
        writer,
        duration_seconds: float | None,
        require_frames: bool = False,
        frames: Sequence[Any] | None = None,
    ) -> EvidenceRecord:
        if require_frames and not frames:
            return self._failed(event_id, media_type, captured_at, "no_frames")
        try:
            path = self._resolve(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
        except (EvidencePathError, OSError):
            self._logger.warning("evidence path rejected for event %s", event_id)
            return self._failed(event_id, media_type, captured_at, "path_error")

        try:
            writer(path)
        except Exception:
            self._logger.warning("evidence encoding failed for event %s", event_id, exc_info=True)
            self._unlink(path)
            return self._failed(event_id, media_type, captured_at, "encode_failed")

        try:
            size = path.stat().st_size
        except OSError:
            self._logger.warning("evidence file missing after write for event %s", event_id)
            return self._failed(event_id, media_type, captured_at, "write_failed")
        if size <= 0:
            self._unlink(path)
            return self._failed(event_id, media_type, captured_at, "empty_file")

        return EvidenceRecord(
            event_id=event_id,
            media_type=media_type,
            status="available",
            relative_path=relative,
            file_size_bytes=size,
            duration_seconds=duration_seconds,
            captured_at=captured_at,
        )

    def _resolve(self, relative: str) -> Path:
        from vision.evidence.paths import resolve_within_root

        return resolve_within_root(self.root, relative)

    def _unlink(self, path: Path) -> None:
        try:
            if path.is_file():
                path.unlink()
        except OSError:  # pragma: no cover - best effort
            pass

    def _failed(
        self, event_id: str, media_type: str, captured_at: datetime, error: str
    ) -> EvidenceRecord:
        return EvidenceRecord(
            event_id=event_id,
            media_type=media_type,
            status="failed",
            relative_path=None,
            file_size_bytes=None,
            duration_seconds=None,
            captured_at=captured_at,
            error=error,
        )
