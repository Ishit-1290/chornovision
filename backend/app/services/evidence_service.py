"""Evidence metadata service and retention policy (Phase 6; FR-38, FR-41, FR-42).

Evidence **bytes** live on the local filesystem under ``EVIDENCE_DIR``; this service owns
every path decision, so no untrusted event field, URL, or filename can control where a file
is read or written (SEC-08, FR-38):

* a relative path is confined to the evidence root (reject absolute paths, ``..`` segments,
  drive letters, and symlinks that resolve outside the root);
* bytes are only reported ``available`` after the backend **verifies the file exists**, so an
  event is never claimed to have evidence that was not finalized (FR-39);
* retention enforces the time window and the storage cap oldest-first, and **never** removes
  a ``protected`` item (active-review evidence). When every remaining candidate is protected
  the run stops and reports the condition rather than deleting protected bytes (FR-42);
* deleting a file is best-effort and only ever targets a resolved path **inside** the root.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.event import Event
from app.models.evidence import Evidence, EvidenceMediaType, EvidenceStatus, RetentionStatus
from app.repositories import events as events_repo
from app.repositories import evidence as evidence_repo
from app.schemas.internal import InternalEvidenceSubmission
from app.utils import ensure_utc, utcnow

LOGGER = logging.getLogger("app.evidence")


class EvidenceServiceError(Exception):
    """Base class for evidence service errors."""


class UnknownEvent(EvidenceServiceError):
    """The evidence references an event id that is not stored."""


class EvidencePathError(EvidenceServiceError):
    """A path escaped the configured evidence directory or is otherwise unsafe."""


class EvidenceNotAvailable(EvidenceServiceError):
    """The evidence has no readable file (pending, failed, or deleted)."""


@dataclass(frozen=True)
class EvidenceRecordResult:
    """Outcome of registering one evidence item."""

    evidence: Evidence
    applied: bool


@dataclass
class RetentionReport:
    """What a retention run did (also returned by the CLI)."""

    deleted: int = 0
    bytes_freed: int = 0
    remaining_bytes: int = 0
    protected_count: int = 0
    blocked_by_protection: bool = False
    skipped_invalid_paths: int = 0
    deleted_ids: list[int] = field(default_factory=list)


def evidence_root() -> Path:
    """Return the configured evidence root (never created here)."""
    return Path(get_settings().evidence_dir).expanduser()


def is_safe_relative_path(relative_path: str) -> bool:
    """True when ``relative_path`` is a non-absolute path with no ``..`` segments."""
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


def resolve_evidence_path(relative_path: str, *, root: Path | None = None) -> Path:
    """Resolve ``relative_path`` inside the evidence root, or raise.

    The resolved, symlink-followed path must stay inside the root; anything else (absolute
    paths, ``..`` traversal, or a symlink pointing outside) raises :class:`EvidencePathError`.
    """
    base = (root or evidence_root()).resolve()
    if not is_safe_relative_path(relative_path):
        raise EvidencePathError("unsafe evidence path")
    candidate = base.joinpath(*relative_path.replace("\\", "/").split("/")).resolve()
    if candidate != base and base not in candidate.parents:
        raise EvidencePathError("evidence path escapes the evidence directory")
    return candidate


def _coerce_media_type(value: str) -> EvidenceMediaType:
    try:
        return EvidenceMediaType(value)
    except ValueError as exc:
        raise EvidenceServiceError(f"unknown media_type {value!r}") from exc


def _register_status(submission: InternalEvidenceSubmission, evidence: Evidence) -> None:
    """Set ``status``/path/size, verifying that 'available' really has a file."""
    evidence.error = None
    if submission.status is EvidenceStatus.PENDING:
        evidence.status = EvidenceStatus.PENDING.value
        evidence.relative_path = submission.relative_path
        evidence.file_size_bytes = submission.file_size_bytes
        evidence.duration_seconds = submission.duration_seconds
        return

    if submission.status is EvidenceStatus.FAILED:
        evidence.status = EvidenceStatus.FAILED.value
        evidence.error = _short_error(submission.error)
        evidence.file_size_bytes = submission.file_size_bytes
        evidence.duration_seconds = submission.duration_seconds
        return

    # status == available: the backend verifies the file before claiming it exists.
    relative_path = submission.relative_path or ""
    try:
        path = resolve_evidence_path(relative_path)
    except EvidencePathError:
        evidence.status = EvidenceStatus.FAILED.value
        evidence.error = "unsafe_path"
        evidence.relative_path = None
        evidence.file_size_bytes = None
        return
    if not path.is_file():
        evidence.status = EvidenceStatus.FAILED.value
        evidence.error = "file_not_found"
        evidence.relative_path = None
        evidence.file_size_bytes = None
        return
    try:
        size = path.stat().st_size
    except OSError:  # pragma: no cover - race with retention
        size = submission.file_size_bytes
    evidence.status = EvidenceStatus.AVAILABLE.value
    evidence.relative_path = relative_path
    # The on-disk size is authoritative over a worker-declared size.
    evidence.file_size_bytes = size if size is not None else submission.file_size_bytes
    evidence.duration_seconds = submission.duration_seconds


def _short_error(value: str | None) -> str:
    text = (value or "capture_failed").strip() or "capture_failed"
    return text[:256]


def register_evidence(db: Session, submission: InternalEvidenceSubmission) -> EvidenceRecordResult:
    """Upsert one evidence item for an event (idempotent per ``(event, media_type)``)."""
    event = events_repo.get_by_event_id(db, submission.event_id)
    if event is None:
        raise UnknownEvent(f"unknown event_id {submission.event_id!r}")

    media_type = _coerce_media_type(submission.media_type)
    captured_at = ensure_utc(submission.captured_at)
    existing = evidence_repo.get_by_event_and_type(db, event.id, media_type.value)

    if existing is None:
        evidence = Evidence(
            event_id=event.id,
            media_type=media_type.value,
            captured_at=captured_at,
            retention_status=RetentionStatus.RETAINED.value,
        )
        _register_status(submission, evidence)
        db.add(evidence)
        db.flush()
        _refresh_evidence_refs(db, event)
        db.commit()
        db.refresh(evidence)
    else:
        existing.captured_at = captured_at
        _register_status(submission, existing)
        # A re-registration never silently un-protects evidence under review.
        if existing.retention_status == RetentionStatus.DELETED.value:
            existing.retention_status = RetentionStatus.RETAINED.value
        db.flush()
        _refresh_evidence_refs(db, event)
        db.commit()
        db.refresh(existing)
        evidence = existing

    if get_settings().evidence_retention_on_register:
        try:
            run_retention(db)
        except Exception:  # pragma: no cover - retention must never break registration
            LOGGER.warning("opportunistic retention run failed", exc_info=True)

    return EvidenceRecordResult(evidence=evidence, applied=True)


def _refresh_evidence_refs(db: Session, event: Event) -> None:
    """Keep the event's denormalised ``evidence_refs`` in sync with its evidence rows."""
    rows = evidence_repo.list_by_event(db, event.id)
    refs = [
        f"{row.media_type}:{row.id}"
        for row in rows
        if row.status == EvidenceStatus.AVAILABLE.value
        and row.retention_status != RetentionStatus.DELETED.value
    ]
    event.evidence_refs = refs


def protect_evidence(db: Session, evidence: Evidence) -> Evidence:
    """Pin evidence so retention never removes it (active review)."""
    if evidence.retention_status != RetentionStatus.DELETED.value:
        evidence.retention_status = RetentionStatus.PROTECTED.value
        db.commit()
        db.refresh(evidence)
    return evidence


def release_evidence(db: Session, evidence: Evidence) -> Evidence:
    """Return pinned evidence to the normal retention lifecycle."""
    if evidence.retention_status == RetentionStatus.PROTECTED.value:
        evidence.retention_status = RetentionStatus.RETAINED.value
        db.commit()
        db.refresh(evidence)
    return evidence


def evidence_file_path(evidence: Evidence) -> Path:
    """Return the readable file for ``evidence`` or raise :class:`EvidenceNotAvailable`."""
    if evidence.retention_status == RetentionStatus.DELETED.value:
        raise EvidenceNotAvailable("evidence has been deleted")
    if evidence.status != EvidenceStatus.AVAILABLE.value or not evidence.relative_path:
        raise EvidenceNotAvailable("evidence is not available")
    path = resolve_evidence_path(evidence.relative_path)
    if not path.is_file():
        raise EvidenceNotAvailable("evidence file is missing")
    return path


def _evict(db: Session, evidence: Evidence, *, now: datetime) -> int:
    """Mark ``evidence`` deleted and best-effort unlink its file. Returns bytes freed."""
    freed = 0
    if evidence.relative_path:
        try:
            path = resolve_evidence_path(evidence.relative_path)
            if path.is_file():
                freed = path.stat().st_size
                path.unlink()
        except EvidencePathError:
            LOGGER.warning("refusing to delete evidence %s outside the evidence root", evidence.id)
            freed = 0
        except OSError:
            freed = 0
    evidence.retention_status = RetentionStatus.DELETED.value
    evidence.deleted_at = now
    return freed


def run_retention(
    db: Session,
    *,
    now: datetime | None = None,
    retention_days: int | None = None,
    storage_limit_bytes: int | None = None,
) -> RetentionReport:
    """Enforce the time window and storage cap, oldest-first, never touching protected rows."""
    settings = get_settings()
    current = ensure_utc(now) if now is not None else utcnow()
    days = settings.evidence_retention_days if retention_days is None else retention_days
    limit = (
        settings.evidence_storage_limit_gb * 1024 * 1024 * 1024
        if storage_limit_bytes is None
        else storage_limit_bytes
    )
    cutoff = current - timedelta(days=days)

    report = RetentionReport()
    candidates = evidence_repo.list_retained(db)  # non-deleted, oldest first
    report.protected_count = sum(
        1 for row in candidates if row.retention_status == RetentionStatus.PROTECTED.value
    )

    # 1. Time-based expiry.
    remaining: list[Evidence] = []
    for row in candidates:
        if row.retention_status == RetentionStatus.PROTECTED.value:
            remaining.append(row)
            continue
        if ensure_utc(row.captured_at) < cutoff:
            report.bytes_freed += _evict(db, row, now=current)
            report.deleted += 1
            report.deleted_ids.append(row.id)
        else:
            remaining.append(row)

    # 2. Storage cap (oldest first), skipping protected rows.
    total = sum(int(row.file_size_bytes or 0) for row in remaining)
    index = 0
    while total > limit:
        while index < len(remaining) and (
            remaining[index].retention_status == RetentionStatus.PROTECTED.value
            or remaining[index].retention_status == RetentionStatus.DELETED.value
        ):
            index += 1
        if index >= len(remaining):
            report.blocked_by_protection = True
            break
        row = remaining[index]
        size = int(row.file_size_bytes or 0)
        report.bytes_freed += _evict(db, row, now=current)
        report.deleted += 1
        report.deleted_ids.append(row.id)
        total -= size
        index += 1

    if report.deleted:
        db.commit()
    report.remaining_bytes = max(0, total)
    return report
