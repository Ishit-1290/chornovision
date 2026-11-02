"""Snapshot/clip encoding behind a small, injectable interface (Phase 6; FR-36).

Encoding is expensive, so it never runs on the frame-processing thread: the evidence
manager hands jobs to a dedicated background worker. OpenCV is imported lazily so the
``vision`` package stays importable and testable without the optional CV dependency; tests
inject a fake encoder instead.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol


class EncodingError(RuntimeError):
    """An image or clip could not be encoded/written."""


class EvidenceEncoder(Protocol):
    """Writes a snapshot or a short clip to a file path."""

    def write_snapshot(self, path: Path, image: Any) -> None: ...

    def write_clip(self, path: Path, frames: Sequence[Any], fps: float) -> None: ...


class OpenCVEncoder:
    """Default encoder using OpenCV (imported lazily)."""

    def write_snapshot(self, path: Path, image: Any) -> None:
        import cv2  # lazy: only needed at capture time

        try:
            written = cv2.imwrite(str(path), image)
        except Exception as exc:  # pragma: no cover - backend dependent
            raise EncodingError("snapshot encoding raised") from exc
        if not written:
            raise EncodingError("snapshot could not be written")

    def write_clip(self, path: Path, frames: Sequence[Any], fps: float) -> None:
        import cv2  # lazy

        if not frames:
            raise EncodingError("no frames to encode")
        first = frames[0]
        shape = getattr(first, "shape", None)
        if shape is None or len(shape) < 2:  # pragma: no cover - guard
            raise EncodingError("frame has no shape")
        height, width = int(shape[0]), int(shape[1])
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(path), fourcc, float(fps), (width, height))
        if not writer.isOpened():  # pragma: no cover - codec dependent
            raise EncodingError("clip writer could not be opened")
        try:
            for frame in frames:
                writer.write(frame)
        except Exception as exc:  # pragma: no cover - backend dependent
            raise EncodingError("clip encoding raised") from exc
        finally:
            writer.release()
