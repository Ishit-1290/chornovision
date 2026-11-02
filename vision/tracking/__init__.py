"""Per-camera multi-object tracking boundary (FR-12, FR-13, FR-14).

Track identifiers are scoped to a single camera and a single connection epoch. The worker
calls :meth:`Tracker.reset` whenever it (re)connects, so track ids are never carried across
a period when the stream was unavailable (FR-08: entry/exit must not be inferred across a
gap). No cross-camera re-identification exists anywhere in this package (CON-02).
"""

from __future__ import annotations

__all__: list[str] = []
