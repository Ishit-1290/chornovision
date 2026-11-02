"""ChronoVision vision worker package (Phase 4).

The vision worker is a **separate runtime** from the FastAPI backend (FR-02, W §3.4):
it connects to camera streams, decodes frames, samples/prepares them, runs pretrained
detection and per-camera tracking, and reports lifecycle state and metrics back to the
backend over the authenticated internal HTTP channel (OQ-09 / D-12).

The backend never runs video inference inside an HTTP handler; it only validates and
persists the state the worker reports.

Entry point::

    python -m vision.runtime

Design boundaries (Phase 4):

- ``vision.net`` — connection-time SSRF enforcement (SEC-06); resolves, validates every
  address, and pins the destination before any connection is opened.
- ``vision.ingestion`` — frame acquisition, bounded queueing, sampling/preparation.
- ``vision.detection`` — pretrained detector boundary (lazy model loading).
- ``vision.tracking`` — per-camera tracker boundary (ByteTrack); no cross-camera IDs.
- ``vision.camera_manager`` — one :class:`CameraWorker` per camera plus the manager.
- ``vision.supervisor`` — reconciles local workers against the backend's *requested*
  monitoring state.
- ``vision.internal_client`` — worker → backend internal HTTP client.
"""

from __future__ import annotations

__all__: list[str] = []
