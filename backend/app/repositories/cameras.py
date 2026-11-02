"""Camera persistence helpers (parameterised queries only)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.camera import Camera, CameraStatus


def add(db: Session, camera: Camera) -> Camera:
    """Persist ``camera`` and return it."""
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


def get_by_id(db: Session, camera_id: int) -> Camera | None:
    """Return the camera with ``camera_id``, or ``None``."""
    return db.get(Camera, camera_id)


def get_by_name(db: Session, name: str) -> Camera | None:
    """Return the camera whose display name matches ``name`` exactly, or ``None``."""
    return db.execute(select(Camera).where(Camera.name == name)).scalar_one_or_none()


def list_all(db: Session) -> list[Camera]:
    """Return every camera ordered by id."""
    return list(db.execute(select(Camera).order_by(Camera.id)).scalars())


def list_by_statuses(db: Session, statuses: set[CameraStatus]) -> list[Camera]:
    """Return cameras whose status is in ``statuses``, ordered by id."""
    values = [status.value for status in statuses]
    return list(
        db.execute(select(Camera).where(Camera.status.in_(values)).order_by(Camera.id)).scalars()
    )


def set_status(db: Session, camera: Camera, status: CameraStatus) -> Camera:
    """Persist a new lifecycle status for ``camera``."""
    camera.status = status.value
    db.commit()
    db.refresh(camera)
    return camera


def save(db: Session, camera: Camera) -> Camera:
    """Commit pending changes to ``camera`` and refresh it."""
    db.commit()
    db.refresh(camera)
    return camera


def count_by_status(db: Session) -> dict[str, int]:
    """Return a mapping of status value to camera count."""
    rows = db.execute(select(Camera.status, func.count()).group_by(Camera.status)).all()
    return {status: int(count) for status, count in rows}
