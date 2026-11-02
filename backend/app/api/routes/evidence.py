"""Authorized evidence delivery and reviewer protection (W §10, SEC-08, FR-38, FR-42).

The evidence directory is **never** served as a static folder. A request must be
authenticated, and the stored relative path is resolved inside ``EVIDENCE_DIR`` before
anything is read, so path traversal and arbitrary file reads are rejected. Only finalized
(``available``) evidence with a real file is served.

Phase 7 adds the reviewer-facing pin/unpin mutation. ``protected`` evidence is never evicted
by retention or storage-cap pressure (D-43), so evidence under active review cannot be
silently deleted. Deletion itself remains an explicit operator action and is not exposed
here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_csrf_auth_context, get_current_user
from app.db import get_db
from app.models.evidence import EvidenceMediaType, EvidenceStatus, RetentionStatus
from app.repositories import audit as audit_repo
from app.repositories import evidence as evidence_repo
from app.schemas.evidence import EvidenceRead, EvidenceRetentionUpdate
from app.services import evidence_service
from app.services.event_broadcaster import get_event_broadcaster

router = APIRouter(
    prefix="/api/evidence",
    tags=["evidence"],
    dependencies=[Depends(get_current_user)],
)

_MEDIA_TYPES = {
    EvidenceMediaType.SNAPSHOT.value: "image/jpeg",
    EvidenceMediaType.CLIP.value: "video/mp4",
}


@router.get("/{evidence_id}")
def get_evidence(evidence_id: int, db: Session = Depends(get_db)) -> FileResponse:
    """Stream one evidence file to an authenticated caller."""
    evidence = evidence_repo.get_by_id(db, evidence_id)
    if evidence is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Evidence not found")

    if evidence.retention_status == RetentionStatus.DELETED.value:
        raise HTTPException(
            status_code=http_status.HTTP_410_GONE, detail="Evidence has been deleted"
        )

    if evidence.status != EvidenceStatus.AVAILABLE.value:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Evidence is not available (status={evidence.status})",
        )

    try:
        path = evidence_service.evidence_file_path(evidence)
    except evidence_service.EvidencePathError as exc:
        # A stored path that escapes the root is treated as missing, never served.
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Evidence file not found"
        ) from exc
    except evidence_service.EvidenceNotAvailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail="Evidence file is missing"
        ) from exc

    media_type = _MEDIA_TYPES.get(evidence.media_type, "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@router.patch("/{evidence_id}", response_model=EvidenceRead)
def update_evidence_retention(
    evidence_id: int,
    payload: EvidenceRetentionUpdate,
    auth: AuthContext = Depends(get_csrf_auth_context),
    db: Session = Depends(get_db),
) -> EvidenceRead:
    """Pin (``protected``) or release (``retained``) one evidence item (FR-42).

    Pinned evidence is excluded from time-based expiry and storage-cap eviction, which is how
    a reviewer preserves evidence while an event is under review. It never deletes anything.
    """
    evidence = evidence_repo.get_by_id(db, evidence_id)
    if evidence is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Evidence not found")

    if evidence.retention_status == RetentionStatus.DELETED.value:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Evidence has been deleted and cannot be re-protected",
        )

    if payload.retention_status.value == RetentionStatus.PROTECTED.value:
        evidence = evidence_service.protect_evidence(db, evidence)
        action = "evidence_protected"
    else:
        evidence = evidence_service.release_evidence(db, evidence)
        action = "evidence_unprotected"

    audit_repo.record(
        db,
        action=action,
        user_id=auth.user.id,
        resource_type="evidence",
        resource_id=str(evidence.id),
        metadata={"event_id": evidence.event_id, "retention_status": evidence.retention_status},
    )
    get_event_broadcaster().publish(
        {
            "type": "evidence",
            "event_id": evidence.event_id,
            "evidence": {
                "id": evidence.id,
                "retention_status": evidence.retention_status,
            },
        }
    )
    return EvidenceRead.model_validate(evidence)
