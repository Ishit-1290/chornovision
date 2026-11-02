"""Frame-acquisition boundary (FR-07).

A :class:`FrameSource` is the only place in the pipeline that talks to a decoder. The
RTSP implementation uses OpenCV's FFmpeg backend, which is the library mandated by the
project (`../workflow_requirements.md` §2). The same class also reads a local video file,
which is how the offline "prerecorded clip" path (W §4, IMPLEMENTATION_PLAN Phase 4) and the
integration tests/benchmarks are exercised — a clip is a legitimate acquisition source even
though the *camera API* only accepts ``rtsp``/``rtsps`` references (D-22).

OpenCV is imported lazily inside the methods so that importing :mod:`vision` never requires
OpenCV to be installed (the backend unit-test suite must stay dependency-free).

The captured frame is tagged with the camera id, the source position (when the decoder
exposes it), the monotonic arrival time, and the wall-clock arrival time — the ingestion
boundary required by FR-07 / G §5.2.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.utils import utcnow


@dataclass
class RawFrame:
    """A decoded frame plus whatever timing the decoder exposes."""

    image: Any
    position_seconds: float | None = None


@dataclass
class Frame:
    """A frame tagged at the ingestion boundary (FR-07)."""

    camera_id: int
    image: Any
    position_seconds: float | None
    arrival_monotonic: float
    arrival_utc: datetime


class FrameSource(Protocol):
    """A frame-acquisition source (RTSP stream or local clip)."""

    def open(self) -> bool:
        """Open the source. Returns ``False`` when it cannot be opened."""

    def read(self) -> RawFrame | None:
        """Return the next frame, or ``None`` on end-of-stream/disconnect/timeout."""

    def close(self) -> None:
        """Release decoder resources. Must be safe to call more than once."""

    @property
    def last_frame_monotonic(self) -> float | None:
        """Monotonic time of the last successful read, or ``None``."""


class OpenCVFrameSource:
    """OpenCV/FFmpeg frame source for an RTSP URL or a local video file.

    ``open_timeout``/``read_timeout`` are applied through OpenCV's FFmpeg timeout
    properties so that a stalled stream makes :meth:`read` return instead of blocking
    forever; the worker additionally uses a watchdog on :attr:`last_frame_monotonic`.
    """

    def __init__(
        self,
        source: str,
        *,
        open_timeout: float = 10.0,
        read_timeout: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source = source
        self._open_timeout = open_timeout
        self._read_timeout = read_timeout
        self._clock = clock
        self._cap: Any | None = None
        self._last_frame: float | None = None
        # ``read`` runs on the capture thread while ``close`` is called from the worker's
        # stop/session-teardown path. Releasing the OpenCV capture from one thread while
        # another is inside ``cap.read()`` frees the FFmpeg context underneath it and
        # segfaults the process. This lock makes ``open``/``read``/``close`` mutually
        # exclusive so the capture is never released under an in-flight read.
        self._lock = threading.Lock()

    def open(self) -> bool:
        import cv2  # lazy: importing vision must not require OpenCV

        cap = cv2.VideoCapture(self._source, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            return False
        # Best-effort timeouts; not all backends honour them.
        try:
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(self._open_timeout * 1000))
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(self._read_timeout * 1000))
        except Exception:  # pragma: no cover - backend dependent
            pass
        with self._lock:
            self._cap = cap
            self._last_frame = None
        return True

    def read(self) -> RawFrame | None:
        import cv2

        with self._lock:
            cap = self._cap
            if cap is None:
                return None
            ok, frame = cap.read()
            if not ok or frame is None:
                return None
            self._last_frame = self._clock()
            position: float | None = None
            try:
                msec = float(cap.get(cv2.CAP_PROP_POS_MSEC))
                if msec > 0:
                    position = msec / 1000.0
            except Exception:  # pragma: no cover - backend dependent
                position = None
            return RawFrame(image=frame, position_seconds=position)

    def close(self) -> None:
        # Blocks until any in-flight ``read`` returns, then releases the capture. This
        # must not race ``read`` (see ``__init__``).
        with self._lock:
            cap = self._cap
            self._cap = None
            if cap is not None:
                try:
                    cap.release()
                except Exception:  # pragma: no cover - release is best-effort
                    pass

    @property
    def last_frame_monotonic(self) -> float | None:
        return self._last_frame


def tag_frame(
    camera_id: int, raw: RawFrame, *, clock: Callable[[], float] = time.monotonic
) -> Frame:
    """Attach ingestion metadata (camera id, timestamps) to a decoded frame."""
    return Frame(
        camera_id=camera_id,
        image=raw.image,
        position_seconds=raw.position_seconds,
        arrival_monotonic=clock(),
        arrival_utc=utcnow(),
    )
