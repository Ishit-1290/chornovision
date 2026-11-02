"""Frame ingestion and preparation (FR-07, FR-09, FR-15, NFR-04, NFR-05).

Boundaries:

- :mod:`vision.ingestion.sources` — the frame-acquisition boundary. The RTSP decoder and
  the offline clip/benchmark reader live here. Decoders are opened lazily so importing this
  package never requires OpenCV.
- :mod:`vision.ingestion.queue` — the bounded per-camera queue and its explicit
  drop-oldest backpressure policy.
- :mod:`vision.ingestion.prepare` — frame validation, the configurable sampling policy,
  and (optional) resizing.

Ingestion is deliberately independent of browser viewing (CON-07): nothing here serves or
publishes frames to a client.
"""

from __future__ import annotations

__all__: list[str] = []
