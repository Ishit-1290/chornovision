"""Worker health vocabulary and state mapping (Phase 4).

The worker's runtime state is exactly the backend's per-camera lifecycle
:class:`~app.models.camera.CameraStatus`, imported rather than duplicated so the two
processes cannot drift apart. This module also defines the small set of machine-readable
"detail" codes the worker attaches to a state report. They are deliberately coarse and
non-sensitive: no stream references, hostnames, credentials, or frame contents.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.camera import CameraStatus

#: The stream reference was rejected by connection-time SSRF enforcement.
DETAIL_INSECURE_TARGET = "insecure_target"
#: The decoder could not open the stream.
DETAIL_OPEN_FAILED = "open_failed"
#: The decoder opened the stream but returned no decodable frame.
DETAIL_READ_FAILED = "read_failed"
#: No frame arrived within the configured read timeout.
DETAIL_STREAM_STALLED = "stream_stalled"
#: The detector model could not be loaded.
DETAIL_DETECTOR_LOAD_FAILED = "detector_load_failed"
#: Bounded recovery gave up (only when ``reconnect_max_attempts`` is non-zero).
DETAIL_RECONNECT_EXHAUSTED = "reconnect_exhausted"
#: The worker is backing off before the next connection attempt.
DETAIL_BACKOFF = "backoff"
#: The worker was stopped on request.
DETAIL_REQUESTED = "requested"


@dataclass(frozen=True)
class WorkerHealth:
    """A point-in-time, non-sensitive snapshot of one camera worker."""

    camera_id: int
    state: CameraStatus
    detail: str | None
    metrics: dict[str, object]
