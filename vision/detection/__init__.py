"""Pretrained detection boundary (FR-10, FR-11).

Detection produces observations only. It never declares a temporal event from a single
frame (FR-11); that belongs to the Phase 5 event engine. The YOLO implementation is loaded
lazily and only when a worker actually starts processing, so importing this package and
running dependency-free tests never downloads or loads model weights.
"""

from __future__ import annotations

__all__: list[str] = []
