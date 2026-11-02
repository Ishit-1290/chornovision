"""Event-linked evidence capture for the vision worker (Phase 6).

Public surface:

* :class:`~vision.evidence.paths.EvidencePathError` /
  :func:`~vision.evidence.paths.build_relative_path` — safe, non-untrusted paths;
* :class:`~vision.evidence.encoding.EvidenceEncoder` /
  :class:`~vision.evidence.encoding.OpenCVEncoder` — injectable encoding;
* :class:`~vision.evidence.store.EvidenceStore` / ``EvidenceRecord`` — bytes on disk;
* :class:`~vision.evidence.manager.EvidenceManager` / ``EvidencePolicy`` — capture windows;
* :class:`~vision.evidence.coordinator.EvidenceCoordinator` — event sink + capture wiring.
"""

from __future__ import annotations

from vision.evidence.coordinator import EvidenceCoordinator
from vision.evidence.encoding import EncodingError, EvidenceEncoder, OpenCVEncoder
from vision.evidence.manager import EvidenceManager, EvidencePolicy
from vision.evidence.paths import (
    EvidencePathError,
    build_relative_path,
    evidence_root,
    is_safe_relative_path,
    resolve_within_root,
    sanitize_component,
)
from vision.evidence.store import EvidenceRecord, EvidenceStore

__all__ = [
    "EncodingError",
    "EvidenceCoordinator",
    "EvidenceEncoder",
    "EvidenceManager",
    "EvidencePathError",
    "EvidencePolicy",
    "EvidenceRecord",
    "EvidenceStore",
    "OpenCVEncoder",
    "build_relative_path",
    "evidence_root",
    "is_safe_relative_path",
    "resolve_within_root",
    "sanitize_component",
]
